import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import TaxChart from "@/components/TaxChart";
import { getMeta, getProperty } from "@/lib/data";
import { addressLine, kindLabel, kindPlural, money, pct, ratioPct, SCORE, shortDate, sqft } from "@/lib/format";
import type { Appeal, Meta, Property } from "@/lib/types";

export const revalidate = 3600;

type Params = { params: Promise<{ pin: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const p = await getProperty((await params).pin);
  return { title: p ? addressLine(p.address, p.unit) : "Property not found" };
}

export default async function PropertyPage({ params }: Params) {
  const { pin } = await params;
  const [p, meta] = await Promise.all([getProperty(pin), getMeta()]);
  if (!p || !meta) notFound();
  const latestYear = Math.max(...Object.keys(p.assessment).map(Number));
  return (
    <>
      <div style={{ display: "grid", gap: 10 }}>
        <Link href="/" className="back">← Search another address</Link>
        <h1>{addressLine(p.address, p.unit)}</h1>
        <div className="facts">
          <span><b>{kindLabel(p.kind)}</b></span>
          {p.sq_ft ? <span><b>{sqft(p.sq_ft)}</b></span> : null}
          {p.year_built ? <span>Built <b>{p.year_built}</b></span> : null}
          {Number.isFinite(latestYear) && <span>{latestYear} assessment <b>{money(p.assessment[latestYear])}</b></span>}
          <span className="small">Block/lot {pin.split("_").slice(1).join(" / ")}</span>
        </div>
      </div>
      <History p={p} meta={meta} />
      <Compare p={p} meta={meta} />
      <AppealCheck p={p} meta={meta} />
    </>
  );
}

function History({ p, meta }: { p: Property; meta: Meta }) {
  const years = Array.from({ length: meta.last_year - p.base_year + 1 }, (_, i) => p.base_year + i);
  const yours = years.map((y) => p.tax[y] ?? null);
  const theirs = years.map((y) => p.compare.median_tax_by_year?.[y] ?? null);
  const flags: Record<number, string> = {};
  for (const y of p.added_assessment_years) flags[y] = "added assessment";
  for (const y of Object.keys(p.appeal_credits)) flags[Number(y)] = "appeal credit";
  const last = p.tax[meta.last_year];
  return (
    <section className="card" aria-labelledby="h-history">
      <header>
        <span className="eyebrow">Your tax over time</span>
        <h2 id="h-history">
          {p.change == null
            ? "Tax history"
            : `Your tax ${p.change >= 0 ? "rose" : "fell"} ${pct(Math.abs(p.change)).replace("+", "")} from ${p.base_year} to ${meta.last_year}`}
        </h2>
      </header>
      <div className="stats">
        <div className="stat you"><span className="k">{meta.last_year} tax</span><span className="v">{money(last)}</span></div>
        <div className="stat you"><span className="k">Your change since {p.base_year}</span><span className="v">{pct(p.change)}</span></div>
        <div className="stat"><span className="k">Similar homes nearby</span><span className="v">{pct(p.compare.median_change)}</span></div>
        <div className="stat">
          <span className="k">Rose more than</span>
          <span className="v">{p.compare.city_percentile == null ? "—" : `${p.compare.city_percentile}%`}</span>
          <span className="small muted">of similar {kindPlural(p.kind)} in the city</span>
        </div>
      </div>
      <TaxChart years={years} yours={yours} theirs={theirs} flags={flags} />
      <div className="legend">
        <span><i style={{ background: "var(--you)" }} />This property</span>
        <span><i style={{ background: "var(--them)" }} />Median of {p.compare.count} similar nearby</span>
        {Object.keys(flags).length > 0 && <span>Large dot: added assessment or appeal credit that year</span>}
      </div>
      {p.added_assessment_years.length > 0 && (
        <p className="note">
          This property received an <b>added assessment</b> in {p.added_assessment_years.join(", ")}. The city sends one
          after renovations or new construction raise a property&apos;s value, so part of the increase came from that work.
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

function Compare({ p, meta }: { p: Property; meta: Meta }) {
  const c = p.compare;
  if (!c.count) {
    return (
      <section className="card" aria-labelledby="h-compare">
        <header><span className="eyebrow">How you compare</span><h2 id="h-compare">No comparison for this property</h2></header>
        <p className="muted">{c.reason}</p>
      </section>
    );
  }
  const band = c.size_band ? Math.round(c.size_band * 100) : null;
  return (
    <section className="card" aria-labelledby="h-compare">
      <header>
        <span className="eyebrow">How you compare</span>
        <h2 id="h-compare">Compared with {c.count} similar {kindPlural(p.kind)} nearby</h2>
        <p className="small muted">
          Same type, within ±{band}% of this property&apos;s floor area, built in the same era, within {c.radius_mi} mile.
          {p.kind === "condo" ? " Other units in the same building come first." : ""}
        </p>
      </header>
      <div className="tablewrap">
        <table>
          <thead><tr><th>Property</th><th className="r">Size</th><th className="r hide-sm">Built</th><th className="r hide-sm">Distance</th><th className="r">Change since {p.base_year}</th></tr></thead>
          <tbody>
            {c.list?.map((n) => (
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
      </div>
      {p.appeals_nearby && p.appeals_nearby.compared > 0 && meta.tax_source === "bills" && (
        <p>
          <b>Appeals nearby:</b> {p.appeals_nearby.won} of these {p.appeals_nearby.compared} properties won a reduction
          since {p.appeals_nearby.since}
          {p.appeals_nearby.median_reduction != null && <>, saving a median {ratioPct(p.appeals_nearby.median_reduction, 0)} of that year&apos;s tax</>}.
        </p>
      )}
    </section>
  );
}

function verdictText(a: Appeal, assessment: number | null, year: number) {
  const r = a.ratio_range!;
  const base = `Similar properties nearby sold for a median ${money(a.median_ppsf)} per square foot. At that rate this property would be worth about ${money(a.estimated_value)}, so its ${money(assessment)} assessment is ${ratioPct(a.ratio)} of value.`;
  if (a.score === "likely")
    return `${base} That is above the ${ratioPct(r.hi, 2)} upper limit the state set for ${year}, so the assessment looks too high.`;
  if (a.score === "possible")
    return a.ratio! > r.hi
      ? `${base} That is above the ${ratioPct(r.hi, 2)} upper limit for ${year}, but the evidence is weaker (see below).`
      : `${base} That is above the city average of ${ratioPct(r.avg, 2)} but inside the allowed range (${ratioPct(r.lo, 2)}–${ratioPct(r.hi, 2)}). An appeal works only if you can show a clearly lower value.`;
  return `${base} That is at or below the city average of ${ratioPct(r.avg, 2)}, so an appeal is unlikely to lower it.${a.ratio! < r.lo ? ` Below ${ratioPct(r.lo, 2)}, the board could even raise it.` : ""}`;
}

function AppealCheck({ p, meta }: { p: Property; meta: Meta }) {
  const a = p.appeal;
  const s = SCORE[a.score];
  const latest = Math.max(...Object.keys(p.assessment).map(Number));
  const assessment = p.assessment[latest] ?? null;
  const scored = a.score === "likely" || a.score === "possible" || a.score === "unlikely";
  return (
    <section className="card" aria-labelledby="h-appeal">
      <header>
        <span className="eyebrow">Appeal check for {meta.ratio_year}</span>
        <h2 id="h-appeal">Could an appeal lower your assessment?</h2>
      </header>
      <div className={`verdict ${s.tone}`}>
        <span className="pill">{s.label}</span>
        <p>{scored ? verdictText(a, assessment, meta.ratio_year) : a.reason}</p>
        {a.notes?.map((n) => <p key={n} className="small">{n}</p>)}
      </div>
      {scored && a.fair_range && a.estimated_value && (
        <RangeBar lo={a.fair_range[0]} hi={a.fair_range[1]} value={a.estimated_value} />
      )}
      {scored && a.fair_range && (
        <p className="small muted">
          Your assessment is in the allowed range if the property was worth between <b>{money(a.fair_range[0])}</b> and{" "}
          <b>{money(a.fair_range[1])}</b> on {new Date(meta.valuation_date + "T12:00:00").toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })}.
          Worth less than {money(a.fair_range[0])}? You may qualify for a reduction.
        </p>
      )}
      {a.comparable_sales && a.comparable_sales.length > 0 && (
        <>
          <h3>Comparable sales used</h3>
          <div className="tablewrap">
            <table>
              <thead><tr><th>Property</th><th className="r hide-sm">Size</th><th className="r hide-sm">Built</th><th className="r">Sold</th><th className="r">Price</th><th className="r">Per sq ft</th><th className="r hide-sm">Distance</th></tr></thead>
              <tbody>
                {a.comparable_sales.map((x, i) => (
                  <tr key={i}>
                    <td>{addressLine(x.address, x.unit)}</td>
                    <td className="r hide-sm">{x.sq_ft.toLocaleString("en-US")}</td>
                    <td className="r hide-sm">{x.year_built ?? "—"}</td>
                    <td className="r">{shortDate(x.sale_date)}</td>
                    <td className="r">{money(x.price)}</td>
                    <td className="r">{money(x.ppsf)}</td>
                    <td className="r hide-sm">{x.miles.toFixed(2)} mi</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small muted">
            Market sales only (the state&apos;s &quot;usable&quot; sale code), similar type, size and age, at most two per
            building. Check each one before you rely on it, and add newer sales close to the valuation date.
          </p>
        </>
      )}
      <p className="small muted">
        A rough screen from public records. It cannot see condition, interior features or renovations that the records
        miss. Not legal or tax advice.
      </p>
      <p><Link className="cta" href="/appeal">How to appeal, step by step →</Link></p>
    </section>
  );
}

function RangeBar({ lo, hi, value }: { lo: number; hi: number; value: number }) {
  const min = Math.min(lo, value) * 0.85, max = Math.max(hi, value) * 1.08;
  const x = (v: number) => `${(((v - min) / (max - min)) * 100).toFixed(2)}%`;
  const k = (v: number) => `$${Math.round(v / 1000).toLocaleString("en-US")}k`;
  return (
    <div className="rangebar" role="img" aria-label={`Estimated value ${money(value)}; the assessment is fair for values from ${money(lo)} to ${money(hi)}`}>
      <div className="axis" />
      <div className="band" style={{ left: x(lo), width: `calc(${x(hi)} - ${x(lo)})` }} />
      <div className="mark" style={{ left: x(value) }} />
      <span className="lab" style={{ left: x(lo) }}>{k(lo)}</span>
      <span className="lab" style={{ left: x(hi) }}>{k(hi)}</span>
      <span className="lab" style={{ left: x(value), top: -16, color: "var(--ink)", fontWeight: 650 }}>Est. {k(value)}</span>
    </div>
  );
}
