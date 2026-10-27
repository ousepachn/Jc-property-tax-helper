"use client";

// The home page map with its two views: the newest bill (default) and the five-year trend.
import { useState } from "react";
import MapView, { type Metric } from "./MapView";

interface Props {
  lastYear: number;
  baseYear: number;
  trendYears: number | null; // null: the data predates the two views (only the change since baseYear)
  medianQ4: number | null;
  median5y: number | null;
  abatedCount: number | null; // null: the data predates abatements
}

const pct = (v: number | null) => (v == null ? null : `${v >= 0 ? "+" : ""}${Math.round(v * 100)}%`);

export default function HomeMap({ lastYear, baseYear, trendYears, medianQ4, median5y, abatedCount }: Props) {
  const legacy = trendYears == null;
  const [metric, setMetric] = useState<Metric>(legacy ? "5y" : "q4");
  const [abated, setAbated] = useState(false);
  const from = legacy ? baseYear : lastYear - trendYears;
  const labels: Record<Metric, string> = {
    q4: `Q4 ${lastYear} bill vs Q4 ${lastYear - 1}`,
    "5y": `Tax ${from}–${lastYear}`,
  };
  const median = metric === "q4" ? pct(medianQ4) : pct(median5y);
  return (
    <section className="mapsec" aria-labelledby="h-map">
      <div className="maphead">
        <div style={{ display: "grid", gap: 6 }}>
          <h2 id="h-map">
            {abated ? "Properties with tax abatements" : metric === "q4" ? "Where the latest bills jumped most" : `Where taxes rose most since ${from}`}
          </h2>
          <p className="muted small">
            {abated ? <>Colored by the abatement law{abatedCount != null && <> · <b className="num">{abatedCount.toLocaleString("en-US")}</b> abated now</>}</>
              : <>{labels[metric]}{median && <> · most properties: <b className="num">{median}</b></>}</>} · select a dot to open it
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
      <MapView metric={metric} label={labels[metric]} abated={abated} />
    </section>
  );
}
