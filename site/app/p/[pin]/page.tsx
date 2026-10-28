import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import AbatementNote from "@/components/Abatement";
import BuildingCompare from "@/components/BuildingCompare";
import MiniMap, { type Marker } from "@/components/MiniMap";
import { PermitAlert } from "@/components/Permits";
import PropertyFeedback from "@/components/PropertyFeedback";
import PropertyHeader from "@/components/PropertyHeader";
import TaxChart from "@/components/TaxChart";
import { getMeta, getProperty } from "@/lib/data";
import { addressLine, kindPlural, money, pct, ratioPct } from "@/lib/format";
import type { Meta, Neighbor, Property } from "@/lib/types";

export const revalidate = 3600;

// Step 1 of a property: what its tax did, and how that compares with similar homes nearby and the city.
// Pages are built on first visit and then served from Vercel's cache for an hour, so repeat visits
// (and scrapers re-reading the same page) don't reach the database.
export async function generateStaticParams() {
  return [];
}

type Params = { params: Promise<{ pin: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const p = await getProperty((await params).pin);
  return { title: p ? addressLine(p.address, p.unit) : "Property not found" };
}

export default async function PropertyPage({ params }: Params) {
  const { pin } = await params;
  const [p, meta] = await Promise.all([getProperty(pin), getMeta()]);
  if (!p || !meta) notFound();
  return (
    <>
      <PropertyHeader p={p} step={1} />
      <BigNumbers p={p} meta={meta} />
      <AbatementNote p={p} />
      <PermitAlert permits={p.permits} pin={p.pin} />
      <History p={p} meta={meta} />
      {p.building_compare && <BuildingCompare b={p.building_compare} address={addressLine(p.address, null)} />}
      {(p.compare.count > 0 || !p.building_compare) && <Compare p={p} meta={meta} />}
      <Link className="next" href={`/p/${p.pin}/appeal`}>
        <div>
          <span className="eyebrow" style={{ color: "inherit", opacity: 0.7 }}>Step 2</span>
          <h2>Is your assessment too high?</h2>
          <p>See your odds on a {meta.ratio_year} appeal, the nearby sales behind them, and the permits and construction on record for this property.</p>
        </div>
        <span className="arrow" aria-hidden="true">→</span>
      </Link>
      <PropertyFeedback pin={p.pin} />
    </>
  );
}

function BigNumbers({ p, meta }: { p: Property; meta: Meta }) {
  const last = meta.last_year;
  const q4 = p.q4_bill?.[last], q4prev = p.q4_bill?.[last - 1];
  const years = meta.trend_years;
  const longChange = years && p.change_5y != null ? p.change_5y : p.change;
  const longFrom = years && p.change_5y != null ? last - years : p.base_year;
  const cls = (v: number | null | undefined) => (v == null ? "" : v > 0 ? "up" : "down");
  return (
    <div className="bignums">
      {q4 != null ? (
        <div className="bignum">
          <span className="k">Q4 {last} bill</span>
          <span className="v">{money(q4)}</span>
          <span className="d">
            {p.change_q4 != null ? <><b className={cls(p.change_q4)}>{pct(p.change_q4)}</b> vs Q4 {last - 1}{q4prev != null && ` (${money(q4prev)})`}</>
              : q4prev != null ? `Q4 ${last - 1}: ${money(q4prev)}` : null}
          </span>
        </div>
      ) : (
        <div className="bignum">
          <span className="k">{last} tax</span>
          <span className="v">{money(p.tax[last])}</span>
          <span className="d">{p.tax_source === "estimated" ? "estimated from the assessment" : "for the year"}</span>
        </div>
      )}
      <div className="bignum">
        <span className="k">Since {longFrom}</span>
        <span className={`v ${cls(longChange)}`}>{pct(longChange)}</span>
        <span className="d">
          {longChange == null && p.abatement?.status === "active" ? "abated: not comparable"
            : longChange == null && p.abatement?.status === "ended" ? `abatement ended in ${p.abatement.year}`
            : `${money(p.tax[longFrom])} → ${money(p.tax[last])} a year`}
        </span>
      </div>
      {p.compare.count === 0 && p.building_compare ? (
        <div className="bignum">
          <span className="k">Assessed vs your building</span>
          <span className={`v ${cls(p.building_compare.vs_floor ?? p.building_compare.vs_median)}`}>
            {pct(p.building_compare.vs_floor ?? p.building_compare.vs_median)}
          </span>
          <span className="d">per sq ft, vs {p.building_compare.vs_floor != null ? "units on similar floors" : "the typical unit"}</span>
        </div>
      ) : (
      <div className="bignum">
        <span className="k">Similar homes nearby, since {p.base_year}</span>
        <span className="v">{pct(p.compare.median_change)}</span>
        <span className="d">
          Yours: {pct(p.change)}
          {p.compare.city_percentile != null && `, a bigger rise than ${p.compare.city_percentile}% of similar ${kindPlural(p.kind)} citywide`}
        </span>
      </div>
      )}
    </div>
  );
}

function History({ p, meta }: { p: Property; meta: Meta }) {
  const years = Array.from({ length: meta.last_year - p.base_year + 1 }, (_, i) => p.base_year + i);
  const yours = years.map((y) => p.tax[y] ?? null);
  const theirs = years.map((y) => p.compare.median_tax_by_year?.[y] ?? null);
  const flags: Record<number, string> = {};
  for (const y of p.added_assessment_years) flags[y] = "added assessment";
  for (const y of Object.keys(p.appeal_credits)) flags[Number(y)] = "appeal credit";
  if (p.abatement?.status === "ended") flags[p.abatement.year] = "abatement ended";
  return (
    <section className="card" aria-labelledby="h-history">
      <header>
        <span className="eyebrow">The trend</span>
        <h2 id="h-history">
          {p.change == null
            ? "Tax history"
            : `Your tax ${p.change >= 0 ? "rose" : "fell"} ${pct(Math.abs(p.change)).replace("+", "")} from ${p.base_year} to ${meta.last_year}`}
        </h2>
      </header>
      <TaxChart years={years} yours={yours} theirs={theirs} flags={flags} />
      <div className="legend">
        <span><i style={{ background: "var(--you)" }} />This property</span>
        {p.compare.count > 0 && <span><i style={{ background: "var(--them)" }} />Median of {p.compare.count} similar nearby</span>}
        {Object.keys(flags).length > 0 && <span>Large dot: {[...new Set(Object.values(flags))].join(", ")} that year</span>}
      </div>
      {p.added_assessment_years.length > 0 && (
        <p className="note">
          This property received an <b>added assessment</b> in {p.added_assessment_years.join(", ")}. The city sends one
          after renovations or new construction raise a property&apos;s value, so part of the increase came from that work.
        </p>
      )}
      {Object.values(p.abatement_charges ?? {}).some(Boolean) && (
        <p className="small muted">
          Includes the abatement charge billed in {Object.entries(p.abatement_charges ?? {}).filter(([, v]) => v).map(([y]) => y).join(", ")}:
          what an abated property pays instead of tax on the building.
        </p>
      )}
      {p.tax_source === "estimated" && (
        <p className="small muted">
          Tax shown is estimated from each year&apos;s assessment and Jersey City&apos;s tax rate. Actual bills can differ
          slightly (abatements, added assessments, credits).
        </p>
      )}
    </section>
  );
}

const SHOW = 5;

function NeighborRows({ list, base }: { list: Neighbor[]; base: number }) {
  return (
    <table>
      <thead><tr><th>Property</th><th className="r">Size</th><th className="r hide-sm">Built</th><th className="r hide-sm">Distance</th><th className="r">Since {base}</th></tr></thead>
      <tbody>
        {list.map((n) => (
          <tr key={n.pin}>
            <td><Link href={`/p/${n.pin}`}>{addressLine(n.address, n.unit)}</Link></td>
            <td className="r">{n.sq_ft?.toLocaleString("en-US")}</td>
            <td className="r hide-sm">{n.year_built ?? "—"}</td>
            <td className="r hide-sm">{n.miles.toFixed(2)} mi</td>
            <td className="r">{pct(n.change)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Compare({ p, meta }: { p: Property; meta: Meta }) {
  const c = p.compare;
  if (!c.count) {
    return (
      <section className="card" aria-labelledby="h-compare">
        <header><span className="eyebrow">Neighbors</span><h2 id="h-compare">No comparison for this property</h2></header>
        <p className="muted">{c.reason}</p>
      </section>
    );
  }
  const band = c.size_band ? Math.round(c.size_band * 100) : null;
  const list = c.list ?? [];
  const markers: Marker[] = list
    .map((n) => ({ pin: n.pin, lat: n.lat, lon: n.lon, kind: "similar" as const, label: `${addressLine(n.address, n.unit)} · ${pct(n.change)}` }))
    .filter((m) => m.lat != null && m.lon != null);
  if (p.lat != null && p.lon != null) {
    markers.push({ pin: p.pin, lat: p.lat, lon: p.lon, kind: "subject", label: addressLine(p.address, p.unit) });
  }
  return (
    <section className="card" aria-labelledby="h-compare">
      <header>
        <span className="eyebrow">Neighbors</span>
        <h2 id="h-compare">Compared with {c.count} similar {kindPlural(p.kind)} nearby</h2>
        <p className="small muted">
          Same type, within ±{band}% of this property&apos;s floor area, built in the same era, within {c.radius_mi} mile.
          {p.kind === "condo" ? " Other units in the same building come first." : ""}
        </p>
      </header>
      {markers.length > 1 && <MiniMap markers={markers} />}
      <div className="tablewrap">
        <NeighborRows list={list.slice(0, SHOW)} base={p.base_year} />
        {list.length > SHOW && (
          <details className="more">
            <summary>Show {list.length - SHOW} more</summary>
            <NeighborRows list={list.slice(SHOW)} base={p.base_year} />
          </details>
        )}
      </div>
      {p.appeals_nearby && p.appeals_nearby.compared > 0 && meta.tax_source === "bills" && (
        <p className="small">
          <b>Appeals nearby:</b> {p.appeals_nearby.won} of these {p.appeals_nearby.compared} properties won a reduction
          since {p.appeals_nearby.since}
          {p.appeals_nearby.median_reduction != null && <>, saving a median {ratioPct(p.appeals_nearby.median_reduction, 0)} of that year&apos;s tax</>}.
        </p>
      )}
    </section>
  );
}
