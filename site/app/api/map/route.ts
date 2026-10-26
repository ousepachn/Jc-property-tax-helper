import { NextResponse } from "next/server";
import { type BBox, mapPoints } from "@/lib/data";

// Parcels for the maps: [pin, lat, lon, change, appeal score]. ?bbox=south,west,north,east limits it to an
// area (the property page's small map). Cached at the edge for a day.
export async function GET(req: Request) {
  const raw = new URL(req.url).searchParams.get("bbox");
  let bbox: BBox | undefined;
  if (raw) {
    const v = raw.split(",").map(Number);
    if (v.length !== 4 || v.some((x) => !Number.isFinite(x)) || v[2] - v[0] > 0.1 || v[3] - v[1] > 0.1) {
      return NextResponse.json({ error: "bbox must be south,west,north,east and at most 0.1 degrees across" }, { status: 400 });
    }
    bbox = v.map((x) => Math.round(x * 1e4) / 1e4) as BBox;   // rounded, so nearby pages share a cache entry
  }
  const points = await mapPoints(bbox);
  return NextResponse.json(points, { headers: { "Cache-Control": "public, s-maxage=86400, stale-while-revalidate=604800" } });
}
