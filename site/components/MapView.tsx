"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { HOODS, hoodOf, per100, type Split } from "@/lib/hoods";
import type { MapPoint } from "@/lib/types";

// Two views: the newest bill (Q4 of the last year vs a year earlier) and the longer trend. Each is
// binned around what most of the city saw (the middle class, a neutral gray), so warm dots rose faster
// than most and blue ones more slowly.
export type Metric = "q4" | "5y";
export const METRIC_COL: Record<Metric, 3 | 4> = { q4: 3, "5y": 4 };
export const BINS: Record<Metric, number[]> = { q4: [0.05, 0.15, 0.25, 0.35, 0.5], "5y": [0.45, 0.6, 0.72, 0.95, 1.3] };
export const COLORS_LIGHT = ["#3b6e91", "#9dbbd0", "#d9d6cf", "#f0b48a", "#d9673a", "#9e2f17"];
export const COLORS_DARK = ["#6fa3c8", "#3f5f75", "#55534f", "#8a5236", "#d0683c", "#f39264"];
const NODATA = { light: "#ecebe7", dark: "#25282b" };

export function bin(change: number | null, bins: number[]) {
  if (change == null) return -1;
  let i = 0;
  while (i < bins.length && change >= bins[i]) i++;
  return i;
}

const pctLabel = (v: number) => `${v >= 0 ? "+" : ""}${Math.round(v * 100)}%`;

// "Abatements only": every other property fades to a faint outline of the city, and abated ones are
// colored by the law they're under (point column 5: 1 long-term, 2 five-year, 3 other, 4 ended recently).
export const ABATEMENT_KINDS = ["Long-term (40A:20)", "Under 40A:21", "Other", "Ended recently"];
const ABATE_LIGHT = ["#6d4bb3", "#1b8a7a", "#c08a12", "#b5473a"];
const ABATE_DARK = ["#a88bf0", "#4fd1bd", "#f0c04a", "#f07c6c"];

export interface Splits { city: Split; hoods: Split[] }

interface View { cx: number; cy: number; scale: number } // cx, cy in mercator units; scale = px per unit

const mercX = (lon: number) => (lon + 180) / 360;
const mercY = (lat: number) => {
  const s = Math.sin((lat * Math.PI) / 180);
  return 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI);
};
const HOOD_XY = HOODS.map((h) => [mercX(h.lon), mercY(h.lat)] as const);

interface Props {
  metric: Metric;
  label: string;
  abated?: boolean;
  hood?: number | null;                       // neighborhood to bring forward; the rest fade
  onHoodHover?: (i: number | null) => void;   // pointer over a neighborhood's name
  onHoodPick?: (i: number) => void;           // click on a neighborhood's name
  onSplits?: (s: Splits) => void;             // per-neighborhood split, recomputed for each metric
}

export default function MapView({ metric, label, abated = false, hood = null, onHoodHover, onHoodPick, onSplits }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const router = useRouter();
  const [points, setPoints] = useState<MapPoint[] | null>(null);
  const [error, setError] = useState(false);
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null);
  const xy = useRef<Float64Array>(new Float64Array());
  const owner = useRef<Int8Array>(new Int8Array());
  const view = useRef<View>({ cx: 0, cy: 0, scale: 1 });
  const dark = useRef(false);
  const [isDark, setIsDark] = useState(false);

  useEffect(() => {
    fetch("/api/map")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((p: MapPoint[]) => {
        const a = new Float64Array(p.length * 2);
        const o = new Int8Array(p.length);
        p.forEach((pt, i) => {
          a[2 * i] = mercX(pt[2]);
          a[2 * i + 1] = mercY(pt[1]);
          o[i] = hoodOf(pt[1], pt[2]);
        });
        xy.current = a;
        owner.current = o;
        setPoints(p);
      })
      .catch(() => setError(true));
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      dark.current = mq.matches;
      setIsDark(mq.matches);
    };
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  // slower / like most / faster, citywide and by neighborhood, for the insight panel
  useEffect(() => {
    if (!points || !onSplits) return;
    const col = METRIC_COL[metric], bins = BINS[metric];
    const tally = Array.from({ length: HOODS.length + 1 }, () => [0, 0, 0]);
    points.forEach((p, i) => {
      const b = bin(p[col], bins);
      if (b < 0) return;
      const k = b <= 1 ? 0 : b === 2 ? 1 : 2;
      tally[HOODS.length][k]++;
      tally[owner.current[i]][k]++;
    });
    onSplits({ city: per100(...(tally[HOODS.length] as [number, number, number])),
      hoods: tally.slice(0, HOODS.length).map((t) => per100(t[0], t[1], t[2])) });
  }, [points, metric, onSplits]);

  const toScreen = (mx: number, my: number, w: number, h: number) => {
    const { cx, cy, scale } = view.current;
    return [(mx - cx) * scale + w / 2, (my - cy) * scale + h / 2] as const;
  };

  const draw = useCallback(() => {
    const c = canvas.current;
    if (!c || !points) return;
    const dpr = window.devicePixelRatio || 1;
    const w = c.clientWidth, h = c.clientHeight;
    if (c.width !== w * dpr || c.height !== h * dpr) {
      c.width = w * dpr;
      c.height = h * dpr;
    }
    const ctx = c.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const { cx, cy, scale } = view.current;
    // about 1.3 px at city view, growing as you zoom in
    const r0 = Math.max(1.3, Math.min(5, scale / 1.8e6));
    const colors = abated ? (dark.current ? ABATE_DARK : ABATE_LIGHT) : dark.current ? COLORS_DARK : COLORS_LIGHT;
    const a = xy.current, o = owner.current, col = METRIC_COL[metric], bins = BINS[metric];
    const classOf = (p: MapPoint) => (abated ? p[5] - 1 : bin(p[col], bins));
    const focus = abated ? null : hood;
    // draw grey (no data, or not abated) first, then "like most", then the rest, so colors stay on top;
    // with a neighborhood in focus, everything outside it goes first and faint
    const order = abated ? [-1, 0, 1, 2, 3] : [-1, 2, 1, 3, 0, 4, 5];
    for (const pass of focus == null ? [0] : [1, 0]) {
      for (const b of order) {
        ctx.fillStyle = b < 0 ? (dark.current ? NODATA.dark : NODATA.light) : colors[b];
        const faint = pass === 1;
        ctx.globalAlpha = faint ? (dark.current ? 0.2 : 0.16) : b < 0 ? (abated ? 0.45 : 0.7) : 1;
        ctx.beginPath();
        for (let i = 0; i < points.length; i++) {
          if (focus != null && (o[i] === focus) === faint) continue;
          if (classOf(points[i]) !== b) continue;
          const x = (a[2 * i] - cx) * scale + w / 2, y = (a[2 * i + 1] - cy) * scale + h / 2;
          if (x < -5 || y < -5 || x > w + 5 || y > h + 5) continue;
          const r = b >= 0 && abated ? Math.max(r0 * 1.6, 2.6) : r0;   // abated dots stand out at city scale
          ctx.moveTo(x + r, y);
          ctx.arc(x, y, r, 0, Math.PI * 2);
        }
        ctx.fill();
      }
    }
    ctx.globalAlpha = 1;
    // neighborhood names, with a halo in the page color
    if (!abated) {
      const st = getComputedStyle(c);
      const ink = st.getPropertyValue("--ink").trim() || "#121212";
      const bg = st.getPropertyValue("--bg").trim() || "#ffffff";
      const accent = st.getPropertyValue("--accent").trim() || "#a8351a";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.lineJoin = "round";
      HOODS.forEach((hd, i) => {
        const [x, y] = toScreen(HOOD_XY[i][0], HOOD_XY[i][1], w, h);
        const on = focus === i;
        ctx.font = `700 ${on ? 16 : 13}px ${st.fontFamily}`;
        ctx.lineWidth = 4;
        ctx.strokeStyle = bg;
        ctx.strokeText(hd.name, x, y);
        ctx.fillStyle = on ? accent : ink;
        ctx.fillText(hd.name, x, y);
      });
    }
  }, [points, metric, abated, hood]); // eslint-disable-line react-hooks/exhaustive-deps

  const fit = useCallback(() => {
    const c = canvas.current;
    const a = xy.current;
    if (!c || !a.length) return;
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    for (let i = 0; i < a.length; i += 2) {
      x0 = Math.min(x0, a[i]); x1 = Math.max(x1, a[i]);
      y0 = Math.min(y0, a[i + 1]); y1 = Math.max(y1, a[i + 1]);
    }
    const s = Math.min(c.clientWidth / (x1 - x0), c.clientHeight / (y1 - y0)) * 0.95;
    view.current = { cx: (x0 + x1) / 2, cy: (y0 + y1) / 2, scale: s };
    draw();
  }, [draw]);

  const drawRef = useRef(draw);
  drawRef.current = draw;
  useEffect(() => {
    draw();
  }, [isDark, draw]);

  useEffect(() => {
    if (!points) return;
    fit();
    const ro = new ResizeObserver(() => drawRef.current());
    if (box.current) ro.observe(box.current);
    return () => ro.disconnect();
  }, [points]); // eslint-disable-line react-hooks/exhaustive-deps

  const zoomAt = (factor: number, px?: number, py?: number) => {
    const c = canvas.current!;
    const w = c.clientWidth, h = c.clientHeight;
    const v = view.current;
    const mx = px ?? w / 2, my = py ?? h / 2;
    const wx = v.cx + (mx - w / 2) / v.scale, wy = v.cy + (my - h / 2) / v.scale;
    const scale = Math.min(Math.max(v.scale * factor, 2000), 5e7);
    view.current = { scale, cx: wx - (mx - w / 2) / scale, cy: wy - (my - h / 2) / scale };
    draw();
  };

  const nearest = (mx: number, my: number) => {
    const c = canvas.current!;
    const { cx, cy, scale } = view.current;
    const w = c.clientWidth, h = c.clientHeight, a = xy.current;
    let best = -1, bd = 64; // within 8 px
    for (let i = 0; i < a.length / 2; i++) {
      if (abated && points && !points[i][5]) continue;
      const dx = (a[2 * i] - cx) * scale + w / 2 - mx, dy = (a[2 * i + 1] - cy) * scale + h / 2 - my;
      const d = dx * dx + dy * dy;
      if (d < bd) { bd = d; best = i; }
    }
    return best;
  };

  // a neighborhood's name under the pointer (within about the width of the word)
  const hoodAt = (mx: number, my: number) => {
    if (abated) return -1;
    const c = canvas.current!;
    for (let i = 0; i < HOODS.length; i++) {
      const [x, y] = toScreen(HOOD_XY[i][0], HOOD_XY[i][1], c.clientWidth, c.clientHeight);
      if (Math.abs(mx - x) < HOODS[i].name.length * 4 + 6 && Math.abs(my - y) < 14) return i;
    }
    return -1;
  };

  // pointer pan, wheel zoom, click to open
  const drag = useRef<{ x: number; y: number; moved: boolean; id: number } | null>(null);
  const hovered = useRef(-1);
  const onDown = (e: React.PointerEvent) => {
    (e.target as Element).setPointerCapture(e.pointerId);
    drag.current = { x: e.clientX, y: e.clientY, moved: false, id: e.pointerId };
  };
  const onMove = (e: React.PointerEvent) => {
    const rect = canvas.current!.getBoundingClientRect();
    const d = drag.current;
    if (d) {
      const dx = e.clientX - d.x, dy = e.clientY - d.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
      if (d.moved) {
        view.current.cx -= dx / view.current.scale;
        view.current.cy -= dy / view.current.scale;
        d.x = e.clientX;
        d.y = e.clientY;
        setTip(null);
        draw();
      }
      return;
    }
    if (e.pointerType !== "mouse" || !points) return;
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    const hi = hoodAt(mx, my);
    if (hi !== hovered.current) {
      hovered.current = hi;
      onHoodHover?.(hi < 0 ? null : hi);
      canvas.current!.style.cursor = hi < 0 ? "" : "pointer";
    }
    if (hi >= 0) return setTip(null);
    const i = nearest(mx, my);
    if (i < 0) return setTip(null);
    const ch = points[i][METRIC_COL[metric]];
    setTip({ x: mx, y: my,
      text: abated ? (points[i][5] === 4 ? "Abatement ended recently" : `Abatement: ${ABATEMENT_KINDS[points[i][5] - 1]}`)
        : ch == null ? "No data for this view" : `${pctLabel(ch)} · ${label}` });
  };
  const onUp = (e: React.PointerEvent) => {
    const d = drag.current;
    drag.current = null;
    if (!d || d.moved || !points) return;
    const rect = canvas.current!.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    const hi = hoodAt(mx, my);
    if (hi >= 0) return onHoodPick?.(hi);
    const i = nearest(mx, my);
    if (i >= 0) router.push(`/p/${points[i][0]}`);
  };
  const onLeave = () => {
    setTip(null);
    if (hovered.current >= 0) {
      hovered.current = -1;
      onHoodHover?.(null);
    }
  };

  useEffect(() => {
    const c = canvas.current;
    if (!c) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = c.getBoundingClientRect();
      zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX - rect.left, e.clientY - rect.top);
    };
    c.addEventListener("wheel", onWheel, { passive: false });
    return () => c.removeEventListener("wheel", onWheel);
  });

  const colors = abated ? (isDark ? ABATE_DARK : ABATE_LIGHT) : isDark ? COLORS_DARK : COLORS_LIGHT;
  const bins = BINS[metric];
  const binLabels = [`Under ${pctLabel(bins[0])}`, `${pctLabel(bins[0])}–${Math.round(bins[1] * 100)}%`, "Like most",
    `${pctLabel(bins[2])}–${Math.round(bins[3] * 100)}%`, `${pctLabel(bins[3])}–${Math.round(bins[4] * 100)}%`, `${pctLabel(bins[4])}+`];
  return (
    <>
      <div className="mapbox" ref={box}>
        <canvas
          ref={canvas}
          role="img"
          aria-label={`Map of Jersey City properties colored by tax change, ${label}. Select a dot to open a property.`}
          onPointerDown={onDown}
          onPointerMove={onMove}
          onPointerUp={onUp}
          onPointerLeave={onLeave}
        />
        {!points && <div className="mapstatus">{error ? "The map could not load. Search by address above." : "Loading map…"}</div>}
        {points && !abated && !points.some((p) => p[METRIC_COL[metric]] != null) && (
          <div className="mapstatus" style={{ pointerEvents: "none" }}>This view needs bill history that isn&apos;t loaded yet.</div>
        )}
        {tip && <div className="maptip" style={{ left: tip.x, top: tip.y }}>{tip.text}</div>}
        <div className="mapctl">
          <button type="button" aria-label="Zoom in" onClick={() => zoomAt(1.6)}>+</button>
          <button type="button" aria-label="Zoom out" onClick={() => zoomAt(1 / 1.6)}>−</button>
          <button type="button" aria-label="Show all of Jersey City" onClick={fit} style={{ fontSize: 13 }}>⤢</button>
        </div>
      </div>
      {abated ? (
        <div className="maplegend">
          <span>Tax abatements</span>
          {ABATEMENT_KINDS.map((k, i) => (
            <span key={k} className="lg"><i style={{ background: colors[i] }} />{k}</span>
          ))}
        </div>
      ) : (
        <div className="maplegend">
          <span>{label}</span>
          <div className="ramp">
            {colors.map((c, i) => <span key={c}><i style={{ background: c }} />{binLabels[i]}</span>)}
          </div>
        </div>
      )}
    </>
  );
}
