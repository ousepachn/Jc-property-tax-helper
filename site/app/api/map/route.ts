import { NextResponse } from "next/server";
import { type BBox, mapPoints } from "@/lib/data";

// Parcels for the maps: [pin, lat, lon, Q4 bill change, 5-year change]. ?bbox=south,west,north,east limits it to an
// area (the property page's small map). Cached at the edge for a day. The box is widened to a 0.01° grid,
// so there are few distinct boxes: nearby pages share cache entries, and varying the box can't make every
// request reach the database.
export async function GET(req: Request) {
  const raw = new URL(req.url).searchParams.get("bbox");
  let bbox: BBox | undefined;
  if (raw) {
    const v = raw.split(",").map(Number);
    const snapped = v.map((x, i) => (i < 2 ? Math.floor(x * 100) : Math.ceil(x * 100)) / 100);
    if (v.length !== 4 || v.some((x) => !Number.isFinite(x)) ||
        snapped[2] - snapped[0] > 0.1 + 1e-9 || snapped[3] - snapped[1] > 0.1 + 1e-9) {
      return NextResponse.json({ error: "bbox must be south,west,north,east and at most 0.1 degrees across" }, { status: 400 });
    }
    bbox = snapped as BBox;
  }
  const points = await mapPoints(bbox);
  return NextResponse.json(points, { headers: { "Cache-Control": "public, s-maxage=86400, stale-while-revalidate=604800" } });
}
