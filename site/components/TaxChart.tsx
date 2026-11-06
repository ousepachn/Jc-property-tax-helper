// Your tax by year next to the median of similar nearby properties. Server-rendered SVG, drawn twice:
// a wide version and a phone version with larger type, so labels stay readable at any width. The lines
// are labeled where they end instead of in a separate legend.

interface Props {
  years: number[];
  yours: (number | null)[];
  theirs: (number | null)[];
  flags: Record<number, string>; // year -> short label (added assessment, appeal credit)
}

// round tick step (1, 2, 2.5 or 5 x 10^n) giving about 4 intervals across the range
function niceStep(v: number) {
  const raw = v / 4, p = Math.pow(10, Math.floor(Math.log10(raw)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= raw) return m * p;
  return raw;
}

const money = (v: number) => `$${Math.round(v).toLocaleString("en-US")}`;
const k = (v: number) =>
  v >= 1000 ? `$${(v / 1000).toLocaleString("en-US", { maximumFractionDigits: v % 1000 ? 1 : 0 })}k` : `$${Math.round(v)}`;

interface Layout { W: number; H: number; L: number; R: number; T: number; B: number; font: number; everyYear: boolean }
const WIDE: Layout = { W: 760, H: 300, L: 56, R: 130, T: 24, B: 32, font: 12, everyYear: true };
const NARROW: Layout = { W: 360, H: 300, L: 40, R: 112, T: 24, B: 32, font: 12.5, everyYear: false };

function Plot({ years, yours, theirs, flags, lay, cls }: Props & { lay: Layout; cls: string }) {
  const { W, H, L, R, T, B } = lay;
  const vals = [...yours, ...theirs].filter((v): v is number => v != null);
  const lo0 = Math.min(...vals), hi0 = Math.max(...vals);
  const step = niceStep(Math.max(hi0 - lo0, hi0 * 0.2));
  const min = Math.max(0, Math.floor((lo0 - step * 0.3) / step) * step), max = Math.ceil((hi0 + step * 0.15) / step) * step;
  const x = (i: number) => L + (years.length === 1 ? (W - L - R) / 2 : (i * (W - L - R)) / (years.length - 1));
  const y = (v: number) => T + (H - T - B) * (1 - (v - min) / (max - min));
  const line = (s: (number | null)[]) => s.map((v, i) => (v == null ? null : `${x(i)},${y(v)}`)).filter(Boolean).join(" ");
  const ticks: number[] = [];
  for (let t = min; t <= max + 1e-6; t += step) ticks.push(t);
  const last = (s: (number | null)[]) => { for (let i = s.length - 1; i >= 0; i--) if (s[i] != null) return i; return -1; };
  const iy = last(yours), it = last(theirs);
  // end labels: keep the two apart when the lines finish close together
  let ly = iy >= 0 ? y(yours[iy]!) : 0, lt = it >= 0 ? y(theirs[it]!) : 0;
  if (iy >= 0 && it >= 0 && Math.abs(ly - lt) < 36) {
    const mid = (ly + lt) / 2, up = ly <= lt;
    ly = mid + (up ? -18 : 18);
    lt = mid + (up ? 18 : -18);
  }
  const showYear = (i: number) => lay.everyYear || i === 0 || i === years.length - 1 || flags[years[i]] != null;
  const shortYear = (yr: number, i: number) => (lay.everyYear && i > 0 && i < years.length - 1 ? `’${String(yr).slice(2)}` : String(yr));
  const fs = lay.font;
  return (
    <svg className={cls} viewBox={`0 0 ${W} ${H}`} role="img"
      aria-label={`Tax by year, ${years[0]} to ${years[years.length - 1]}: this property${iy >= 0 ? ` ${money(yours[iy]!)} in ${years[iy]}` : ""}${it >= 0 ? `; median of similar nearby ${money(theirs[it]!)}` : ""}`}>
      {ticks.map((t) => (
        <g key={t}>
          <line className="axis" x1={L} x2={W - R} y1={y(t)} y2={y(t)} />
          <text x={L - 8} y={y(t) + 4} textAnchor="end" style={{ fontSize: fs }}>{k(t)}</text>
        </g>
      ))}
      <line className="base" x1={L} x2={W - R} y1={H - B} y2={H - B} />
      {years.map((yr, i) => showYear(i) && (
        <text key={yr} x={x(i)} y={H - 10} textAnchor="middle" style={{ fontSize: fs }}>{shortYear(yr, i)}</text>
      ))}
      {Object.keys(flags).map(Number).filter((yr) => years.includes(yr)).map((yr) => {
        const i = years.indexOf(yr);
        return (
          <g key={yr}>
            <line x1={x(i)} x2={x(i)} y1={T} y2={H - B} stroke="var(--ink)" strokeWidth={1} strokeDasharray="2 3" />
            <text x={x(i) < (L + W - R) / 2 ? x(i) + 6 : x(i) - 6} y={T + 10} textAnchor={x(i) < (L + W - R) / 2 ? "start" : "end"}
              className="lab val" style={{ fontSize: fs }}>{flags[yr]}</text>
          </g>
        );
      })}
      <polyline points={line(theirs)} fill="none" stroke="var(--them)" strokeWidth={2.5} />
      <polyline points={line(yours)} fill="none" stroke="var(--you)" strokeWidth={3} />
      {yours.map((v, i) => v == null ? null : (
        <circle key={i} cx={x(i)} cy={y(v)} r={flags[years[i]] ? 5 : i === iy ? 4.5 : 0} fill="var(--you)">
          <title>{`${years[i]}: ${money(v)}${flags[years[i]] ? ` (${flags[years[i]]})` : ""}`}</title>
        </circle>
      ))}
      {it >= 0 && <circle cx={x(it)} cy={y(theirs[it]!)} r={4} fill="var(--them)" />}
      {iy >= 0 && (
        <g>
          <text x={x(iy) + 10} y={ly - 2} className="lab you" style={{ fontSize: fs + 1 }}>This property</text>
          <text x={x(iy) + 10} y={ly + 14} className="val" style={{ fontSize: fs + 1 }}>{money(yours[iy]!)}</text>
        </g>
      )}
      {it >= 0 && (
        <g>
          <text x={x(it) + 10} y={lt - 2} className="lab" style={{ fontSize: fs + 1 }}>Similar nearby</text>
          <text x={x(it) + 10} y={lt + 14} className="val" style={{ fontSize: fs + 1 }}>{money(theirs[it]!)}</text>
        </g>
      )}
    </svg>
  );
}

export default function TaxChart(props: Props) {
  if (![...props.yours, ...props.theirs].some((v) => v != null)) return null;
  return (
    <div className="chart">
      <Plot {...props} lay={WIDE} cls="chart-wide" />
      <Plot {...props} lay={NARROW} cls="chart-narrow" />
    </div>
  );
}
