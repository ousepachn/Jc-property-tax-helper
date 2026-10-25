import { NextResponse } from "next/server";
import { mapPoints } from "@/lib/data";

// All parcels for the map: [pin, lat, lon, change, appeal score]. Cached at the edge for a day.
export async function GET() {
  const points = await mapPoints();
  return NextResponse.json(points, { headers: { "Cache-Control": "public, s-maxage=86400, stale-while-revalidate=604800" } });
}
