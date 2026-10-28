// Where the site's data comes from: the `site` schema in Neon Postgres (production, read-only role),
// or a folder written by `python pipeline/build_site.py --json-out` (local development).
// Imported only by server components and route handlers.
//
// Every query here is a single read, so it goes over Neon's HTTP endpoint (@neondatabase/serverless):
// no connections to pool or leak in serverless functions, and it works wherever HTTPS does.
import { neon } from "@neondatabase/serverless";
import { promises as fs } from "fs";
import path from "path";
import type { MapPoint, Meta, Property, SearchHit } from "./types";

const DB_URL = process.env.SITE_DATABASE_URL;
// local development only: keep the bundler from tracing the whole project through this path
const DATA_DIR = path.resolve(/*turbopackIgnore: true*/ process.cwd(), process.env.SITE_DATA_DIR || "data");

const sql = DB_URL ? neon(DB_URL) : null;

// --- local JSON files ----------------------------------------------------------------------------

type IndexFile = { fields: string[]; rows: (string | number | null)[][] };
let indexCache: Promise<IndexFile> | null = null;

function readJson<T>(file: string): Promise<T> {
  return fs.readFile(path.join(DATA_DIR, file), "utf8").then((t) => JSON.parse(t) as T);
}

function localIndex() {
  indexCache ??= readJson<IndexFile>("index.json");
  return indexCache;
}

// same hash as build_site.shard_of
function shardOf(pin: string, n = 64) {
  let h = 0;
  for (const ch of pin) h = (Math.imul(h, 31) + ch.charCodeAt(0)) >>> 0;
  return h % n;
}

// --- shared --------------------------------------------------------------------------------------

export function normalizeQuery(q: string) {
  return q.toUpperCase().replace(/[^A-Z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
}

// Words people type that the tax records spell differently. Each search word matches if the address
// contains it or one of these (addresses are matched by substring, so ST also finds STREET).
const ALIASES: Record<string, string[]> = {
  STREET: ["ST"], AVENUE: ["AVE"], AV: ["AVE"], BOULEVARD: ["BLVD"], PLACE: ["PL"], DRIVE: ["DR"], ROAD: ["RD"],
  TERRACE: ["TER"], COURT: ["CT"], LANE: ["LN"], PARKWAY: ["PKWY"], HIGHWAY: ["HWY"], SQUARE: ["SQ"],
  JFK: ["KENNEDY"], MLK: ["KING"],
};
// Numbered streets: Jersey City's roll mostly spells them out ("349 SEVENTH ST"), people type "7th".
const ORDINALS = ["FIRST", "SECOND", "THIRD", "FOURTH", "FIFTH", "SIXTH", "SEVENTH", "EIGHTH", "NINTH", "TENTH",
  "ELEVENTH", "TWELFTH", "THIRTEENTH", "FOURTEENTH", "FIFTEENTH", "SIXTEENTH", "SEVENTEENTH", "EIGHTEENTH"];
ORDINALS.forEach((word, i) => {
  const n = i + 1, digits = `${n}${n % 10 === 1 && n !== 11 ? "ST" : n % 10 === 2 && n !== 12 ? "ND" : n % 10 === 3 && n !== 13 ? "RD" : "TH"}`;
  ALIASES[word] = [digits];
  ALIASES[digits] = [word];
});

export interface ParsedQuery {
  terms: string[][]; // each word with its alternatives
  unit: string | null; // unit number typed, normalized like unitKey(); "" = asked for units, none typed yet
  implicitUnit: boolean; // the unit was guessed from a trailing number, not marked (Unit, Apt, #, comma)
}

// how a condo unit is matched: the county's C0310 -> 310, C003L -> 3L, C0PHG -> PHG; typed 03L -> 3L
export function unitKey(u: string) {
  return u.toUpperCase().replace(/^C(?=\w{4})/, "").replace(/[^A-Z0-9]/g, "").replace(/^0+(?=\w)/, "");
}

const UNIT_WORD = String.raw`(?:#|\b(?:UNIT|APT|APARTMENT|STE|SUITE)\b\.?)`;
const UNIT_MARK = new RegExp(String.raw`(?:,\s*${UNIT_WORD}?|${UNIT_WORD})\s*([A-Z0-9-]*)\s*$`);

export function parseQuery(q: string): ParsedQuery {
  let s = q.toUpperCase().replace(/\bJERSEY CITY\b|\bNJ\b|\b07\d{3}\b/g, " ").trim().replace(/,$/, "");
  let unit: string | null = null;
  let implicitUnit = false;
  const m = s.match(UNIT_MARK);
  if (m && normalizeQuery(s.slice(0, m.index)).length) {
    unit = unitKey(m[1] ?? "");
    s = s.slice(0, m.index);
  }
  const words = normalizeQuery(s).split(" ").filter(Boolean);
  // "77 Hudson St 1205": a trailing number after a house number and street is the unit
  const last = words[words.length - 1];
  if (unit === null && words.length >= 3 && /^\d/.test(words[0]) && /\d/.test(last) && !/^\d+(ST|ND|RD|TH)$/.test(last)) {
    unit = unitKey(words.pop()!);
    implicitUnit = true;
  }
  return { terms: words.map((w) => [w, ...(ALIASES[w] ?? [])]), unit, implicitUnit };
}

function matches(address: string, terms: string[][]) {
  const a = normalizeQuery(address);
  return terms.every((alts) => alts.some((t) => a.includes(t)));
}

// the house number typed first ranks exact address starts first: "77" before "177" or "770"
function startsWithNumber(address: string, terms: string[][]) {
  const n = terms[0]?.[0];
  return n && /^\d/.test(n) ? normalizeQuery(address).startsWith(`${n} `) : false;
}

const SEARCH_LIMIT = 10;

export async function search(q: string): Promise<SearchHit[]> {
  const p = parseQuery(q);
  if (!p.terms.length) return [];
  if (p.unit !== null) {
    const hits = await searchUnits(p);
    if (hits.length || !p.implicitUnit) return hits;
    // the trailing number wasn't a unit after all ("100 Grove St 2" where 2 is part of nothing): search it as text
    return searchAddresses({ ...p, terms: [...p.terms, [p.unit]], unit: null });
  }
  return searchAddresses(p);
}

const UNIT_SQL = `regexp_replace(regexp_replace(upper(coalesce(unit, '')), '^C(?=\\w{4})', ''), '^0+(?=\\w)', '')`;

function termsSql(terms: string[][], params: unknown[]) {
  return terms
    .map((alts) => `(${alts.map((t) => { params.push(`%${t}%`); return `upper(address) LIKE $${params.length}`; }).join(" OR ")})`)
    .join(" AND ");
}

// One row per street address: a condo building shows once, with its unit count.
async function searchAddresses(p: ParsedQuery): Promise<SearchHit[]> {
  if (sql) {
    const params: unknown[] = [];
    const where = termsSql(p.terms, params);
    params.push(`${p.terms[0][0]} %`);
    const starts = params.length;
    params.push(SEARCH_LIMIT);
    const rows = await sql.query(
      `SELECT address, count(*)::int AS n, count(unit)::int AS u, min(pin) AS pin, min(unit) AS unit, min(kind) AS kind
       FROM site.properties WHERE ${where} GROUP BY address
       ORDER BY bool_or(upper(address) LIKE $${starts}) DESC, length(address), address LIMIT $${params.length}`,
      params,
    );
    return (rows as { address: string; n: number; u: number; pin: string; unit: string | null; kind: string | null }[]).map((r) =>
      r.n > 1 ? { pin: "", address: r.address, unit: null, kind: r.kind, units: r.u || r.n } : { pin: r.pin, address: r.address, unit: r.unit, kind: r.kind },
    );
  }
  const idx = await localIndex();
  const by = new Map<string, SearchHit & { n: number; u: number }>();
  for (const r of idx.rows) {
    const address = String(r[1]);
    if (!matches(address, p.terms)) continue;
    const g = by.get(address);
    const hasUnit = r[2] ? 1 : 0;
    if (g) { g.n++; g.u += hasUnit; }
    else by.set(address, { pin: String(r[0]), address, unit: (r[2] as string) ?? null, kind: (r[3] as string) ?? null, n: 1, u: hasUnit });
  }
  return [...by.values()]
    .sort((a, b) => Number(startsWithNumber(b.address, p.terms)) - Number(startsWithNumber(a.address, p.terms)) ||
      a.address.length - b.address.length || a.address.localeCompare(b.address))
    .slice(0, SEARCH_LIMIT)
    .map(({ n, u, ...h }) => (n > 1 ? { ...h, pin: "", unit: null, units: u || n } : h));
}

// Units at the matching address(es), by unit number; "" lists a building's units in order. The building's
// own lot (the common elements, no unit number) is left out.
async function searchUnits(p: ParsedQuery): Promise<SearchHit[]> {
  const u = p.unit ?? "";
  if (sql) {
    const params: unknown[] = [];
    const where = termsSql(p.terms, params);
    params.push(`${u}%`);
    const like = params.length;
    params.push(u);
    const exact = params.length;
    params.push(`${p.terms[0][0]} %`);
    const starts = params.length;
    params.push(SEARCH_LIMIT);
    const rows = await sql.query(
      `SELECT pin, address, unit, kind FROM site.properties
       WHERE ${where} AND unit IS NOT NULL AND ${UNIT_SQL} LIKE $${like}
       ORDER BY (upper(address) LIKE $${starts}) DESC, length(address), address, (${UNIT_SQL} = $${exact}) DESC,
                length(${UNIT_SQL}), ${UNIT_SQL}
       LIMIT $${params.length}`,
      params,
    );
    return rows as SearchHit[];
  }
  const idx = await localIndex();
  const hits: SearchHit[] = [];
  for (const r of idx.rows) {
    const unit = (r[2] as string) ?? null;
    if (unit && matches(String(r[1]), p.terms) && unitKey(unit).startsWith(u)) {
      hits.push({ pin: String(r[0]), address: String(r[1]), unit, kind: (r[3] as string) ?? null });
    }
  }
  const k = (h: SearchHit) => unitKey(h.unit ?? "");
  hits.sort((a, b) => Number(startsWithNumber(b.address, p.terms)) - Number(startsWithNumber(a.address, p.terms)) ||
    a.address.length - b.address.length || a.address.localeCompare(b.address) ||
    Number(k(b) === u) - Number(k(a) === u) || k(a).length - k(b).length || k(a).localeCompare(k(b)));
  return hits.slice(0, SEARCH_LIMIT);
}

export async function getProperty(pin: string): Promise<Property | null> {
  if (!/^\d{4}_[\w.]+$/.test(pin)) return null;
  if (sql) {
    const rows = await sql`SELECT data FROM site.properties WHERE pin = ${pin}`;
    return (rows[0]?.data as Property) ?? null;
  }
  try {
    const shard = await readJson<Record<string, Property>>(`p/${shardOf(pin)}.json`);
    return shard[pin] ?? null;
  } catch {
    return null;
  }
}

export async function getMeta(): Promise<Meta | null> {
  if (sql) {
    const rows = await sql`SELECT value FROM site.meta WHERE key = '0906'`;
    return (rows[0]?.value as Meta) ?? null;
  }
  try {
    return await readJson<Meta>("meta.json");
  } catch {
    return null;
  }
}

export type BBox = [number, number, number, number]; // south, west, north, east

export async function mapPoints(bbox?: BBox): Promise<MapPoint[]> {
  if (sql) {
    const area = bbox ? "AND lat BETWEEN $1 AND $3 AND lon BETWEEN $2 AND $4" : "";
    const query = (cols: string) =>
      sql.query(`SELECT pin, lat, lon, ${cols} FROM site.properties WHERE lat IS NOT NULL ${area}`, bbox ?? [], { arrayMode: true });
    // change_q4 / change_5y arrive with the next data build; until then show the long-run change
    const rows = await query("change_q4, change_5y, coalesce(abatement, 0)").catch(() => query("NULL, change, 0"));
    return rows as MapPoint[];
  }
  const idx = await localIndex();
  const col = (name: string) => idx.fields.indexOf(name);
  const q4 = col("change_q4"), y5 = col("change_5y"), ab = col("abatement"), lat = col("lat"), lon = col("lon");
  return idx.rows
    .filter((r) => r[lat] != null)
    .map((r): MapPoint => [String(r[0]), Number(r[lat]), Number(r[lon]),
      q4 >= 0 ? ((r[q4] as number) ?? null) : null, y5 >= 0 ? ((r[y5] as number) ?? null) : ((r[col("change")] as number) ?? null),
      ab >= 0 ? Number(r[ab] ?? 0) : 0])
    .filter((p) => !bbox || (p[1] >= bbox[0] && p[1] <= bbox[2] && p[2] >= bbox[1] && p[2] <= bbox[3]));
}
