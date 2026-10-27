"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import type { MapPoint } from "@/lib/types";

// Two views: the newest bill (Q4 of the last year vs a year earlier) and the longer trend. Each is
// binned around what most of the city saw, so the warm colors are the biggest increases.
export type Metric = "q4" | "5y";
export const METRIC_COL: Record<Metric, 3 | 4> = { q4: 3, "5y": 4 };
const BINS: Record<Metric, number[]> = { q4: [0.05, 0.15, 0.25, 0.35, 0.5], "5y": [0.2, 0.45, 0.7, 0.95, 1.3] };
const COLORS_LIGHT = ["#2b6f9e", "#6ea6c9", "#c9d0d3", "#e9a35c", "#d4622b", "#a3301b"];
const COLORS_DARK = ["#5aa4d6", "#3d6f8f", "#4a5961", "#b27839", "#d5703c", "#e9553b"];

function bin(change: number | null, bins: number[]) {
  if (change == null) return -1;
  let i = 0;
  while (i < bins.length && change >= bins[i]) i++;
  return i;
}

const pctLabel = (v: number) => `${v >= 0 ? "+" : ""}${Math.round(v * 100)}%`;

interface View { cx: number; cy: number; scale: number } // cx, cy in mercator units; scale = px per unit

const mercX = (lon: number) => (lon + 180) / 360;
const mercY = (lat: number) => {
  const s = Math.sin((lat * Math.PI) / 180);
  return 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI);
};

export default function MapView({ metric, label }: { metric: Metric; label: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const router = useRouter();
  const [points, setPoints] = useState<MapPoint[] | null>(null);
  const [error, setError] = useState(false);
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null);
  const xy = useRef<Float64Array>(new Float64Array());
  const view = useRef<View>({ cx: 0, cy: 0, scale: 1 });
  const dark = useRef(false);
  const [isDark, setIsDark] = useState(false);

  useEffect(() => {
    fetch("/api/map")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((p: MapPoint[]) => {
        const a = new Float64Array(p.length * 2);
        p.forEach((pt, i) => {
          a[2 * i] = mercX(pt[2]);
          a[2 * i + 1] = mercY(pt[1]);
        });
        xy.current = a;
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

  useEffect(() => {
    draw();
  }, [isDark, metric]); // eslint-disable-line react-hooks/exhaustive-deps

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
    // about 1.5 px at city view, growing as you zoom in
    const r = Math.max(1.1, Math.min(5, scale / 2e6));
    const colors = dark.current ? COLORS_DARK : COLORS_LIGHT;
    const a = xy.current, col = METRIC_COL[metric], bins = BINS[metric];
    // draw grey (no data) first, then each bin, so colors stay on top
    for (let b = -1; b < colors.length; b++) {
      ctx.fillStyle = b < 0 ? (dark.current ? "#334047" : "#dfe5e9") : colors[b];
      ctx.beginPath();
      for (let i = 0; i < points.length; i++) {
        if (bin(points[i][col], bins) !== b) continue;
        const x = (a[2 * i] - cx) * scale + w / 2, y = (a[2 * i + 1] - cy) * scale + h / 2;
        if (x < -5 || y < -5 || x > w + 5 || y > h + 5) continue;
        ctx.moveTo(x + r, y);
        ctx.arc(x, y, r, 0, Math.PI * 2);
      }
      ctx.fill();
    }
  }, [points, metric]);

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

  useEffect(() => {
    if (!points) return;
    fit();
    const ro = new ResizeObserver(() => draw());
    if (box.current) ro.observe(box.current);
    return () => ro.disconnect();
  }, [points, fit, draw]);

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
      const dx = (a[2 * i] - cx) * scale + w / 2 - mx, dy = (a[2 * i + 1] - cy) * scale + h / 2 - my;
      const d = dx * dx + dy * dy;
      if (d < bd) { bd = d; best = i; }
    }
    return best;
  };

  // pointer pan, wheel zoom, click to open
  const drag = useRef<{ x: number; y: number; moved: boolean; id: number } | null>(null);
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
    const i = nearest(e.clientX - rect.left, e.clientY - rect.top);
    if (i < 0) return setTip(null);
    const ch = points[i][METRIC_COL[metric]];
    setTip({ x: e.clientX - rect.left, y: e.clientY - rect.top,
      text: ch == null ? "No data for this view" : `${pctLabel(ch)} · ${label}` });
  };
  const onUp = (e: React.PointerEvent) => {
    const d = drag.current;
    drag.current = null;
    if (!d || d.moved || !points) return;
    const rect = canvas.current!.getBoundingClientRect();
    const i = nearest(e.clientX - rect.left, e.clientY - rect.top);
    if (i >= 0) router.push(`/p/${points[i][0]}`);
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

  const colors = isDark ? COLORS_DARK : COLORS_LIGHT;
  return (
    <div className="mapbox" ref={box}>
      <canvas
        ref={canvas}
        role="img"
        aria-label={`Map of Jersey City properties colored by tax change, ${label}. Select a dot to open a property.`}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerLeave={() => setTip(null)}
      />
      {!points && <div className="mapstatus">{error ? "The map could not load. Search by address above." : "Loading map…"}</div>}
      {points && !points.some((p) => p[METRIC_COL[metric]] != null) && (
        <div className="mapstatus" style={{ pointerEvents: "none" }}>This view needs bill history that isn&apos;t loaded yet.</div>
      )}
      {tip && <div className="maptip" style={{ left: tip.x, top: tip.y }}>{tip.text}</div>}
      <div className="mapctl">
        <button type="button" aria-label="Zoom in" onClick={() => zoomAt(1.6)}>+</button>
        <button type="button" aria-label="Zoom out" onClick={() => zoomAt(1 / 1.6)}>−</button>
        <button type="button" aria-label="Show all of Jersey City" onClick={fit} style={{ fontSize: 13 }}>⤢</button>
      </div>
      <div className="maplegend">
        <span>{label}</span>
        <div className="ramp">{colors.map((c) => <span key={c} style={{ background: c }} />)}</div>
        <div className="ends">
          <span>&lt;{pctLabel(BINS[metric][0])}</span>
          <span>{pctLabel(BINS[metric][2])}</span>
          <span>{pctLabel(BINS[metric][4])}+</span>
        </div>
      </div>
    </div>
  );
}
