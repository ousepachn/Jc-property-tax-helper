import type { Score } from "./types";

export const money = (v: number | null | undefined) =>
  v == null ? "—" : v.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

export const pct = (v: number | null | undefined, digits = 0) =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;

export const ratioPct = (v: number | null | undefined, digits = 1) => (v == null ? "—" : `${(v * 100).toFixed(digits)}%`);

export const sqft = (v: number | null | undefined) => (v == null ? "—" : `${v.toLocaleString("en-US")} sq ft`);

export function unitLabel(unit: string | null) {
  if (!unit) return "";
  const m = unit.match(/^C0*(\d+\w*)$/);
  return m ? `Unit ${m[1]}` : unit;
}

export function addressLine(address: string, unit: string | null) {
  const a = address.replace(/\.$/, "").replace(/\b(\w)(\w*)/g, (_, f: string, r: string) => f + r.toLowerCase());
  return unit ? `${a}, ${unitLabel(unit)}` : a;
}

const KIND: Record<string, string> = {
  single_family: "Single-family home",
  "2_family": "2-family home",
  "3_family": "3-family home",
  "4_family": "4-family home",
  condo: "Condo",
};
const KIND_PLURAL: Record<string, string> = {
  single_family: "single-family homes",
  "2_family": "2-family homes",
  "3_family": "3-family homes",
  "4_family": "4-family homes",
  condo: "condos",
};
export const kindLabel = (k: string | null) => (k ? KIND[k] ?? k : "Property");
export const kindPlural = (k: string | null) => (k ? KIND_PLURAL[k] ?? "properties" : "properties");

export const SCORE: Record<Score, { label: string; tone: "good" | "warn" | "bad" | "muted" }> = {
  likely: { label: "Likely worth appealing", tone: "good" },
  possible: { label: "Possibly worth appealing", tone: "warn" },
  unlikely: { label: "Appeal unlikely to help", tone: "bad" },
  not_enough_data: { label: "Not enough data", tone: "muted" },
  not_applicable: { label: "Not scored", tone: "muted" },
};

export function shortDate(iso: string) {
  const d = new Date(iso + "T12:00:00");
  return d.toLocaleDateString("en-US", { month: "short", year: "numeric" });
}

export const PERMIT_CATEGORY: Record<string, string> = {
  new_construction: "New construction",
  addition: "Addition",
  renovation: "Renovation or alteration",
  demolition: "Demolition",
  certificate: "Certificate of occupancy",
  minor: "Repair or equipment",
  other: "Other",
};

export const RELEVANCE: Record<string, string> = {
  likely: "Likely raises assessment",
  possible: "May raise assessment",
  unlikely: "Usually no tax change",
  lower: "May lower assessment",
};

export const isoDate = (iso: string | null | undefined) =>
  iso ? new Date(iso + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "—";

export const LAW: Record<string, { short: string; long: string }> = {
  long_term: { short: "Long-term", long: "a long-term tax abatement (N.J.S.A. 40A:20, up to 30 years)" },
  five_year: { short: "5-year", long: "a five-year tax abatement (N.J.S.A. 40A:21)" },
  affordable: { short: "Affordable housing", long: "an affordable-housing tax exemption" },
  urban_renewal: { short: "Urban renewal", long: "an urban-renewal tax abatement (older law)" },
  other: { short: "Other", long: "a partial tax exemption" },
};

export const monthYear = (iso: string | null | undefined) =>
  iso ? new Date(iso + "T12:00:00").toLocaleDateString("en-US", { month: "short", year: "numeric" }) : null;

// $48.8B, $1.30B, $250M, $12,000
export function bigMoney(v: number | null | undefined) {
  if (v == null) return "—";
  if (v >= 1e9) return `$${(v / 1e9).toFixed(v >= 1e10 ? 1 : 2)}B`;
  if (v >= 1e6) return `$${Math.round(v / 1e6)}M`;
  return money(v);
}
