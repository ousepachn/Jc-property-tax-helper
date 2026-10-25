import { NextResponse } from "next/server";
import { search } from "@/lib/data";

export async function GET(req: Request) {
  const q = new URL(req.url).searchParams.get("q") ?? "";
  if (q.trim().length < 2) return NextResponse.json([]);
  const hits = await search(q.slice(0, 80));
  return NextResponse.json(hits, { headers: { "Cache-Control": "public, s-maxage=3600, stale-while-revalidate=86400" } });
}
