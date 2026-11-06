"use client";

// The home page map with its two views (the newest bill, the longer trend), a neighborhood picker and an
// insight panel. Every figure in the panel is "out of every 100 properties", so areas compare directly.
import { useCallback, useState } from "react";
import { HOODS, type Split } from "@/lib/hoods";
import MapView, { type Metric, type Splits } from "./MapView";

interface Props {
  lastYear: number;
  baseYear: number;
  trendYears: number | null; // null: the data predates the two views (only the change since baseYear)
  medianQ4: number | null;
  median5y: number | null;
  abatedCount: number | null; // null: the data predates abatements
}

const pct = (v: number | null) => (v == null ? null : `${v >= 0 ? "+" : ""}${Math.round(v * 100)}%`);
const SWATCH = { slower: "var(--slower)", same: "var(--same)", faster: "var(--faster)" };

function Waffle({ s }: { s: Split }) {
  const cells = [
    ...Array(s.faster).fill(SWATCH.faster), ...Array(s.same).fill(SWATCH.same), ...Array(s.slower).fill(SWATCH.slower),
  ];
  return (
    <div className="waffle" role="img" aria-label={`Of every 100 properties: ${s.faster} rose faster, ${s.same} like most, ${s.slower} more slowly`}>
      {cells.map((c, i) => <i key={i} style={{ background: c }} />)}
    </div>
  );
}

export default function HomeMap({ lastYear, baseYear, trendYears, medianQ4, median5y, abatedCount }: Props) {
  const legacy = trendYears == null;
  const [metric, setMetric] = useState<Metric>(legacy ? "5y" : "q4");
  const [abated, setAbated] = useState(false);
  const [picked, setPicked] = useState<number | null>(null);
  const [hover, setHover] = useState<number | null | undefined>(undefined);
  const [splits, setSplits] = useState<Splits | null>(null);
  const onSplits = useCallback((s: Splits) => setSplits(s), []);
  const from = legacy ? baseYear : lastYear - trendYears;
  const labels: Record<Metric, string> = {
    q4: `Q4 ${lastYear} bill vs Q4 ${lastYear - 1}`,
    "5y": `Tax ${from}–${lastYear}`,
  };
  const median = metric === "q4" ? pct(medianQ4) : pct(median5y);
  const sel = hover !== undefined ? hover : picked;
  const period = metric === "q4" ? "this year" : `since ${from}`;

  // the sentence and note for the selected area
  let who = "The whole city", head = "", note = "", split: Split | null = null;
  if (splits) {
    const c = splits.city;
    if (sel == null) {
      split = c;
      head = `${c.faster} of every 100 properties saw their tax rise faster than most of the city ${period}.`;
      note = `Most moved in step with the city${median ? `, about ${median}` : ""}: ${c.same} of every 100. The rest split ${c.faster} faster and ${c.slower} more slowly.`;
    } else {
      const s = splits.hoods[sel], name = HOODS[sel].name;
      const fasters = splits.hoods.map((h) => h.faster), slowers = splits.hoods.map((h) => h.slower);
      who = name;
      split = s;
      head = s.slower >= 25
        ? `${name} is mixed: ${s.faster} of every 100 properties rose faster than most of the city ${period}, and ${s.slower} more slowly.`
        : `In ${name}, ${s.faster} of every 100 properties rose faster than most of the city ${period}.`;
      const rank = s.faster === Math.max(...fasters) ? "The highest share of any neighborhood. "
        : s.faster === Math.min(...fasters) ? "The lowest share of any neighborhood. " : "";
      const slow = s.slower === Math.max(...slowers) && s.slower >= 25
        ? `That is the most slower-rising properties anywhere, and ${s.same} of every 100 moved in step with the city.`
        : `${s.slower} of every 100 rose more slowly; ${s.same} moved in step with the city.`;
      note = `${rank}Citywide, ${c.faster} of every 100 rose faster. ${slow}`;
    }
  }
  const order = splits ? HOODS.map((_, i) => i).sort((a, b) => splits.hoods[b].faster - splits.hoods[a].faster) : [];
  const rows: { i: number | null; name: string; short: string; s: Split }[] = splits
    ? [{ i: null, name: "The whole city", short: "City", s: splits.city },
      ...order.map((i) => ({ i, name: HOODS[i].name, short: HOODS[i].short, s: splits.hoods[i] }))]
    : [];

  return (
    <section className="mapsec" aria-labelledby="h-map">
      <div className="maphead">
        <div style={{ display: "grid", gap: 6, maxWidth: 760 }}>
          <h2 id="h-map">
            {abated ? "Properties with tax abatements" : metric === "q4" ? "Where the latest bills outpaced the city" : `Where taxes outpaced the city since ${from}`}
          </h2>
          <p className="muted small">
            {abated ? <>Colored by the abatement law{abatedCount != null && <> · <b className="num">{abatedCount.toLocaleString("en-US")}</b> abated now</>}</>
              : <>Every property, colored by how its tax changed: {labels[metric]}. Most moved about {median ?? "the same"}, in step with the city; warm dots rose faster, blue ones more slowly. Select a dot to open it.</>}
          </p>
        </div>
        <div className="mapctls">
          {!legacy && !abated && (
            <div className="toggle" role="group" aria-label="Map view">
              <button type="button" aria-pressed={metric === "q4"} onClick={() => setMetric("q4")}>Q4 {lastYear}</button>
              <button type="button" aria-pressed={metric === "5y"} onClick={() => setMetric("5y")}>Last {trendYears} years</button>
            </div>
          )}
          {abatedCount != null && (
            <button type="button" className="filter" aria-pressed={abated} onClick={() => setAbated((v) => !v)}>
              Abatements only
            </button>
          )}
        </div>
      </div>

      <div className="mapgrid">
        <div className="mapcol">
          <MapView metric={metric} label={labels[metric]} abated={abated} hood={sel}
            onHoodHover={(i) => setHover(i == null ? undefined : i)} onHoodPick={(i) => { setPicked(i); setHover(undefined); }}
            onSplits={onSplits} />
        </div>

        {!abated && split && (
          <div className="insights">
            <div className="hoodtabs" role="group" aria-label="Neighborhood">
              {rows.map((r) => (
                <button key={r.short} type="button" aria-pressed={sel === r.i} onClick={() => { setPicked(r.i); setHover(undefined); }}>{r.short}</button>
              ))}
            </div>

            <div className="hoodlist">
              <div className="hd"><span style={{ fontWeight: 600 }}>Compare neighborhoods</span><span>Faster, of every 100</span></div>
              {rows.map((r) => (
                <button key={r.name} type="button" aria-pressed={sel === r.i}
                  onClick={() => { setPicked(r.i); setHover(undefined); }}
                  onMouseEnter={() => setHover(r.i)} onMouseLeave={() => setHover(undefined)}
                  onFocus={() => setHover(r.i)} onBlur={() => setHover(undefined)}>
                  <span>{r.name}</span>
                  <span className="bar" aria-hidden="true">
                    <i style={{ width: `${r.s.slower}%`, background: SWATCH.slower }} />
                    <i style={{ width: `${r.s.same}%`, background: SWATCH.same }} />
                    <i style={{ width: `${r.s.faster}%`, background: SWATCH.faster }} />
                  </span>
                  <span className="n">{r.s.faster}</span>
                </button>
              ))}
              <p className="small muted" style={{ marginTop: 8, fontSize: 12.5 }}>
                Hover a neighborhood here or on the map to see it; click to keep it selected. Neighborhoods are approximate:
                each property counts toward the nearest of six centers, roughly the city&apos;s six wards.
              </p>
            </div>
            <div className="insight" aria-live="polite">
              <span className="who">{who}</span>
              <p className="head">{head}</p>
              <div className="split3">
                <Waffle s={split} />
                <dl className="counts">
                  <dt><i style={{ background: SWATCH.faster }} />Rose faster</dt><dd>{split.faster}</dd>
                  <dt><i style={{ background: SWATCH.same }} />Like most</dt><dd>{split.same}</dd>
                  <dt><i style={{ background: SWATCH.slower }} />Rose more slowly</dt><dd>{split.slower}</dd>
                  <dt className="per">Out of every 100 properties</dt>
                </dl>
              </div>
              <p className="note">{note}</p>
            </div>

          </div>
        )}
      </div>
    </section>
  );
}
