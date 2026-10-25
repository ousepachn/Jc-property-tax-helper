"use client";

// Small map for a property page: the property, its similar properties and its comparable sales,
// over the parcels around them for context.
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import type { MapPoint } from "@/lib/types";

export interface Marker {
  pin: string;
  lat: number;
  lon: number;
  label: string;
  kind: "subject" | "similar" | "sale";
}

const KM_PER_DEG = 111.32;

export default function MiniMap({ markers }: { markers: Marker[] }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const router = useRouter();
  const [context, setContext] = useState<MapPoint[]>([]);
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null);

  // view: fit every marker, at least about 0.25 mile across
  const lats = markers.map((m) => m.lat), lons = markers.map((m) => m.lon);
  const midLat = (Math.min(...lats) + Math.max(...lats)) / 2;
  const kx = Math.cos((midLat * Math.PI) / 180);
  const minSpan = 0.4 / KM_PER_DEG;
  const spanLat = Math.max(Math.max(...lats) - Math.min(...lats), minSpan) * 1.3;
  const spanLon = Math.max(Math.max(...lons) - Math.min(...lons), minSpan / kx) * 1.3;
  const cLat = midLat, cLon = (Math.min(...lons) + Math.max(...lons)) / 2;

  useEffect(() => {
    // the map is wider than tall: cover up to 3:1 so the context fills the whole width
    const halfLat = spanLat * 0.6, halfLon = Math.max(spanLon * 0.6, (spanLat / kx) * 1.6);
    const bbox = [cLat - halfLat, cLon - halfLon, cLat + halfLat, cLon + halfLon].map((v) => v.toFixed(4));
    fetch(`/api/map?bbox=${bbox.join(",")}`)
      .then((r) => (r.ok ? r.json() : []))
      .then(setContext)
      .catch(() => {});
  }, [cLat, cLon, spanLat, spanLon, kx]);

  const project = (w: number, h: number) => {
    const s = Math.min(w / (spanLon * kx), h / spanLat);
    return (lat: number, lon: number) => [w / 2 + (lon - cLon) * kx * s, h / 2 - (lat - cLat) * s] as const;
  };

  useEffect(() => {
    const c = canvas.current;
    if (!c) return;
    const draw = () => {
      const dpr = window.devicePixelRatio || 1, w = c.clientWidth, h = c.clientHeight;
      c.width = w * dpr;
      c.height = h * dpr;
      const ctx = c.getContext("2d")!;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const css = getComputedStyle(c);
      const col = (v: string) => css.getPropertyValue(v).trim();
      const P = project(w, h);
      ctx.fillStyle = col("--line");
      ctx.beginPath();
      for (const p of context) {
        const [x, y] = P(p[1], p[2]);
        ctx.moveTo(x + 2, y);
        ctx.arc(x, y, 2, 0, Math.PI * 2);
      }
      ctx.fill();
      for (const kind of ["similar", "sale", "subject"] as const) {
        for (const m of markers.filter((mm) => mm.kind === kind)) {
          const [x, y] = P(m.lat, m.lon);
          ctx.lineWidth = 2;
          ctx.strokeStyle = col("--surface");
          if (kind === "similar") {
            ctx.fillStyle = col("--them");
            ctx.beginPath(); ctx.arc(x, y, 5.5, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
          } else if (kind === "sale") {
            ctx.fillStyle = col("--warn");
            ctx.fillRect(x - 5.5, y - 5.5, 11, 11); ctx.strokeRect(x - 5.5, y - 5.5, 11, 11);
          } else {
            ctx.fillStyle = col("--accent");
            ctx.beginPath(); ctx.arc(x, y, 8, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
            ctx.strokeStyle = col("--accent");
            ctx.beginPath(); ctx.arc(x, y, 13, 0, Math.PI * 2); ctx.stroke();
          }
        }
      }
      // scale bar: 0.1 mile
      const s = Math.min(w / (spanLon * kx), h / spanLat);
      const px = (0.1 * 1.609344 / KM_PER_DEG) * s;
      ctx.strokeStyle = col("--muted"); ctx.fillStyle = col("--muted"); ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(12, h - 14); ctx.lineTo(12 + px, h - 14); ctx.stroke();
      ctx.font = "12px system-ui, sans-serif";
      ctx.fillText("0.1 mi", 12, h - 20);
    };
    draw();
    const ro = new ResizeObserver(draw);
    ro.observe(c);
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", draw);
    return () => { ro.disconnect(); mq.removeEventListener("change", draw); };
  });

  const hit = (e: React.PointerEvent) => {
    const c = canvas.current!, r = c.getBoundingClientRect();
    const P = project(c.clientWidth, c.clientHeight);
    let best: Marker | null = null, bd = 144;
    for (const m of markers) {
      const [x, y] = P(m.lat, m.lon);
      const d = (x - (e.clientX - r.left)) ** 2 + (y - (e.clientY - r.top)) ** 2;
      if (d < bd) { bd = d; best = m; }
    }
    return { best, x: e.clientX - r.left, y: e.clientY - r.top };
  };

  return (
    <div style={{ display: "grid", gap: 8 }}>
      <div className="minimap">
        <canvas
          ref={canvas}
          role="img"
          aria-label="Map of this property, its similar properties and its comparable sales"
          onPointerMove={(e) => {
            const { best, x, y } = hit(e);
            setTip(best ? { x, y, text: best.label } : null);
          }}
          onPointerLeave={() => setTip(null)}
          onClick={(e) => {
            const { best } = hit(e as unknown as React.PointerEvent);
            if (best && best.kind !== "subject") router.push(`/p/${best.pin}`);
          }}
        />
        {tip && <div className="maptip" style={{ left: tip.x, top: tip.y }}>{tip.text}</div>}
      </div>
      <div className="legend">
        <span><i className="dot" style={{ background: "var(--accent)" }} />This property</span>
        <span><i className="dot" style={{ background: "var(--them)" }} />Similar properties</span>
        {markers.some((m) => m.kind === "sale") && <span><i className="sq" style={{ background: "var(--warn)" }} />Comparable sales</span>}
      </div>
    </div>
  );
}
