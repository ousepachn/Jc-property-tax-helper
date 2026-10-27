// Citywide figures from the county tax roll: what's taxable, who carries it, and how much is abated.
import { bigMoney, ratioPct } from "@/lib/format";
import type { CityStats as Stats } from "@/lib/types";

const SHARE_COLORS = ["var(--accent)", "#c08a12", "#6d4bb3", "#b5473a", "#8a969d", "#c9d0d3"];

export default function CityStats({ c, year, asOf }: { c: Stats; year: number; asOf: string | null }) {
  const a = c.abatement;
  return (
    <section className="city" aria-labelledby="h-city">
      <header style={{ display: "grid", gap: 6 }}>
        <h2 id="h-city">Jersey City&apos;s tax roll</h2>
        <p className="muted small">
          {year} assessments from the Hudson County Board of Taxation{asOf ? `, as of ${asOf}` : ""}. Assessed values, not market values.
        </p>
      </header>
      <div className="bignums">
        <div className="bignum">
          <span className="k">Taxable assessed value</span>
          <span className="v">{bigMoney(c.taxable_value)}</span>
          <span className="d">{c.records.toLocaleString("en-US")} properties and units on the roll</span>
        </div>
        <div className="bignum">
          <span className="k">{year} tax it raises, about</span>
          <span className="v">{bigMoney(c.levy_estimate)}</span>
          <span className="d">at ${c.rate.toFixed(3)} per $100 of assessment</span>
        </div>
        <div className="bignum">
          <span className="k">Exempt public and nonprofit property</span>
          <span className="v">{bigMoney(c.exempt_value)}</span>
          <span className="d">government, schools, religious and charitable</span>
        </div>
      </div>
      <div style={{ display: "grid", gap: 10 }}>
        <h3>Who carries the taxable value</h3>
        <div className="sharebar" role="img" aria-label={c.by_class.map((g) => `${g.label} ${ratioPct(g.share, 0)}`).join(", ")}>
          {c.by_class.map((g, i) => <span key={g.label} style={{ width: `${(g.share ?? 0) * 100}%`, background: SHARE_COLORS[i] }} />)}
        </div>
        <div className="sharelegend">
          {c.by_class.map((g, i) => (g.share ?? 0) < 0.005 ? null : (
            <span key={g.label}><i style={{ background: SHARE_COLORS[i] }} />{g.label} <b>{ratioPct(g.share, 0)}</b></span>
          ))}
        </div>
      </div>
      <div style={{ display: "grid", gap: 10 }}>
        <h3>Tax abatements</h3>
        <div className="bignums">
          <div className="bignum">
            <span className="k">Properties with an abatement</span>
            <span className="v">{a.properties.toLocaleString("en-US")}</span>
            <span className="d">{a.units.toLocaleString("en-US")} condo units in {a.buildings.toLocaleString("en-US")} {a.buildings === 1 ? "building" : "buildings"}; {a.full} whole {a.full === 1 ? "project" : "projects"}</span>
          </div>
          <div className="bignum">
            <span className="k">Assessed value exempt by abatements</span>
            <span className="v">{bigMoney(a.value)}</span>
            <span className="d">{ratioPct(a.share_of_value, 1)} of all assessed value; regular tax on it would be about {bigMoney(a.regular_tax_equivalent)} a year</span>
          </div>
          <div className="bignum">
            <span className="k">Ending by {a.ending_by}</span>
            <span className="v">{a.ending_soon.toLocaleString("en-US")}</span>
            <span className="d">and {a.ended_recently.toLocaleString("en-US")} ended since {a.ended_since}, now paying full tax</span>
          </div>
        </div>
        <p className="small muted">
          Abated owners pay a negotiated annual charge instead of regular tax on the building, so &quot;regular tax&quot; above
          is not money the city loses one-for-one. Counts are from exemption records on the tax roll.
        </p>
      </div>
    </section>
  );
}
