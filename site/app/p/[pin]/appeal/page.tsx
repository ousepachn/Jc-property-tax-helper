import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { PermitHistory } from "@/components/Permits";
import PropertyHeader from "@/components/PropertyHeader";
import { getMeta, getProperty } from "@/lib/data";
import { addressLine, money, ratioPct, SCORE, shortDate } from "@/lib/format";
import type { Appeal, Meta, Property } from "@/lib/types";

export const revalidate = 3600;

// Step 2 of a property: could an appeal help, the comparable sales behind that, and the permit history
// (work that raised the value explains a higher assessment, and finished work can still bring an added one).
export async function generateStaticParams() {
  return [];
}

type Params = { params: Promise<{ pin: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const p = await getProperty((await params).pin);
  return { title: p ? `Appeal check · ${addressLine(p.address, p.unit)}` : "Property not found" };
}

export default async function AppealStep({ params }: Params) {
  const { pin } = await params;
  const [p, meta] = await Promise.all([getProperty(pin), getMeta()]);
  if (!p || !meta) notFound();
  return (
    <>
      <PropertyHeader p={p} step={2} />
      <AppealCheck p={p} meta={meta} />
      <PermitHistory permits={p.permits} meta={meta} />
      <p className="muted">
        Ready to file? <Link href="/appeal">The appeal guide</Link> has the {meta.ratio_year} deadlines, forms and fees.
      </p>
    </>
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
