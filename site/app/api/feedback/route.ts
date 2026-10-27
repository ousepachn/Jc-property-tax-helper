// Receive one piece of feedback from the /feedback form. Public, so: a hidden honeypot field for bots,
// length limits, and a few submissions per address per 10 minutes (per server instance).
import { NextResponse } from "next/server";
import { getProperty } from "@/lib/data";
import { feedbackConfigured, LIMITS, saveFeedback, TOPICS, type Topic } from "@/lib/feedback";
import { addressLine } from "@/lib/format";

const WINDOW_MS = 10 * 60 * 1000, MAX_PER_WINDOW = 5;
const recent = new Map<string, number[]>();

function limited(ip: string) {
  const now = Date.now();
  const times = (recent.get(ip) ?? []).filter((t) => now - t < WINDOW_MS);
  times.push(now);
  recent.set(ip, times);
  if (recent.size > 5000) recent.clear();
  return times.length > MAX_PER_WINDOW;
}

const text = (v: unknown, max: number) => (typeof v === "string" ? v.trim().slice(0, max) : "");

// lets a deploy check be made without submitting anything
export async function GET() {
  return NextResponse.json({ ok: feedbackConfigured() });
}

export async function POST(req: Request) {
  if (!feedbackConfigured()) return NextResponse.json({ error: "Feedback isn't set up yet." }, { status: 503 });
  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Bad request" }, { status: 400 });
  }
  if (text(body.website, 100)) return NextResponse.json({ ok: true }); // honeypot: a bot filled the hidden field
  const ip = (req.headers.get("x-forwarded-for") ?? "").split(",")[0].trim() || "unknown";
  if (limited(ip)) return NextResponse.json({ error: "Too many messages. Please try again in a few minutes." }, { status: 429 });

  const topic = (typeof body.topic === "string" && body.topic in TOPICS ? body.topic : "other") as Topic;
  const message = text(body.message, LIMITS.message);
  const email = text(body.email, LIMITS.email);
  if (message.length < 3) return NextResponse.json({ error: "Please write a few words." }, { status: 400 });
  if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return NextResponse.json({ error: "That email address doesn't look right." }, { status: 400 });
  }
  const pin = text(body.pin, 40);
  const p = pin ? await getProperty(pin) : null;
  await saveFeedback({
    received_at: new Date().toISOString(),
    topic, message, email: email || null,
    pin: p ? p.pin : null, address: p ? addressLine(p.address, p.unit) : null,
    query: text(body.query, LIMITS.query) || null,
    page: text(body.page, LIMITS.page) || null,
    user_agent: (req.headers.get("user-agent") ?? "").slice(0, 200) || null,
  });
  return NextResponse.json({ ok: true });
}
