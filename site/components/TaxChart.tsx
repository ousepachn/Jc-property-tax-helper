// Your tax by year next to the median of similar nearby properties. Server-rendered SVG.

interface Props {
  years: number[];
  yours: (number | null)[];
  theirs: (number | null)[];
  flags: Record<number, string>; // year -> short label (added assessment, appeal credit)
}

const W = 480, H = 220, L = 56, R = 22, T = 14, B = 30;

// round tick step (1, 2, 2.5 or 5 x 10^n) giving about 4 intervals up to the data maximum
function niceStep(v: number) {
  const raw = v / 4, p = Math.pow(10, Math.floor(Math.log10(raw)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= raw) return m * p;
  return raw;
}

export default function TaxChart({ years, yours, theirs, flags }: Props) {
  const vals = [...yours, ...theirs].filter((v): v is number => v != null);
  if (!vals.length) return null;
  const top = Math.max(...vals) * 1.05, step = niceStep(top), max = Math.ceil(top / step) * step;
  const x = (i: number) => L + (years.length === 1 ? (W - L - R) / 2 : (i * (W - L - R)) / (years.length - 1));
  const y = (v: number) => T + (H - T - B) * (1 - v / max);
  const line = (s: (number | null)[]) =>
    s.map((v, i) => (v == null ? null : `${x(i)},${y(v)}`)).filter(Boolean).join(" ");
  const ticks: number[] = [];
  for (let t = 0; t <= max + 1e-6; t += step) ticks.push(t);
  const k = (v: number) =>
    v >= 1000 ? `$${(v / 1000).toLocaleString("en-US", { maximumFractionDigits: v % 1000 ? 1 : 0 })}k` : `$${Math.round(v)}`;
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Tax by year: this property and the median of similar nearby properties">
        {ticks.map((t) => (
          <g key={t}>
            <line className="axis" x1={L} x2={W - R} y1={y(t)} y2={y(t)} />
            <text x={L - 8} y={y(t) + 4} textAnchor="end">{k(t)}</text>
          </g>
        ))}
        {years.map((yr, i) => (
          <text key={yr} x={x(i)} y={H - 12} textAnchor="middle">{yr}</text>
        ))}
        <polyline points={line(theirs)} fill="none" stroke="var(--them)" strokeWidth={2.5} strokeDasharray="5 4" />
        <polyline points={line(yours)} fill="none" stroke="var(--you)" strokeWidth={3} />
        {yours.map((v, i) =>
          v == null ? null : (
            <circle key={i} cx={x(i)} cy={y(v)} r={flags[years[i]] ? 5.5 : 3.5} fill="var(--you)"
              stroke={flags[years[i]] ? "var(--surface)" : "none"} strokeWidth={2}>
              <title>{`${years[i]}: $${Math.round(v).toLocaleString("en-US")}${flags[years[i]] ? ` (${flags[years[i]]})` : ""}`}</title>
            </circle>
          ),
        )}
      </svg>
    </div>
  );
}
