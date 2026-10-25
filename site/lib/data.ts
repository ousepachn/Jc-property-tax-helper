// Where the site's data comes from: the `site` schema in Postgres (production, read-only role),
// or a folder written by `python pipeline/build_site.py --json-out` (local development).
// Imported only by server components and route handlers.
import { promises as fs } from "fs";
import path from "path";
import postgres from "postgres";
import type { MapPoint, Meta, Property, Score, SearchHit } from "./types";

const DB_URL = process.env.SITE_DATABASE_URL;
const DATA_DIR = path.resolve(process.cwd(), process.env.SITE_DATA_DIR || "data");

const sql = DB_URL ? postgres(DB_URL, { prepare: false, max: 3, idle_timeout: 20, connect_timeout: 10 }) : null;

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

function matches(address: string, terms: string[]) {
  const a = normalizeQuery(address);
  return terms.every((t) => a.includes(t));
}

export async function search(q: string, limit = 8): Promise<SearchHit[]> {
  const terms = normalizeQuery(q).split(" ").filter(Boolean);
  if (!terms.length) return [];
  if (sql) {
    const where = terms.reduce((acc, t) => sql`${acc} AND upper(address) LIKE ${"%" + t + "%"}`, sql`TRUE`);
    const rows = await sql<SearchHit[]>`
      SELECT pin, address, unit, kind FROM site.properties WHERE ${where}
      ORDER BY length(address), address, unit NULLS FIRST LIMIT ${limit}`;
    return rows;
  }
  const idx = await localIndex();
  const hits: SearchHit[] = [];
  for (const r of idx.rows) {
    if (matches(String(r[1]), terms)) {
      hits.push({ pin: String(r[0]), address: String(r[1]), unit: (r[2] as string) ?? null, kind: (r[3] as string) ?? null });
    }
  }
  hits.sort((a, b) => a.address.length - b.address.length || a.address.localeCompare(b.address) ||
    (a.unit ?? "").localeCompare(b.unit ?? ""));
  return hits.slice(0, limit);
}

export async function getProperty(pin: string): Promise<Property | null> {
  if (!/^\d{4}_[\w.]+$/.test(pin)) return null;
  if (sql) {
    const rows = await sql<{ data: Property }[]>`SELECT data FROM site.properties WHERE pin = ${pin}`;
    return rows[0]?.data ?? null;
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
    const rows = await sql<{ value: Meta }[]>`SELECT value FROM site.meta WHERE key = '0906'`;
    return rows[0]?.value ?? null;
  }
  try {
    return await readJson<Meta>("meta.json");
  } catch {
    return null;
  }
}

export async function mapPoints(): Promise<MapPoint[]> {
  if (sql) {
    const rows = await sql<{ pin: string; lat: number; lon: number; change: number | null; appeal: Score | null }[]>`
      SELECT pin, lat, lon, change, appeal FROM site.properties WHERE lat IS NOT NULL`;
    return rows.map((r) => [r.pin, r.lat, r.lon, r.change, r.appeal]);
  }
  const idx = await localIndex();
  return idx.rows
    .filter((r) => r[4] != null)
    .map((r) => [String(r[0]), Number(r[4]), Number(r[5]), (r[7] as number) ?? null, (r[8] as Score) ?? null]);
}
