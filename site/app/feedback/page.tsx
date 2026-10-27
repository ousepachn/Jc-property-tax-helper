import type { Metadata } from "next";
import Link from "next/link";
import FeedbackForm from "@/components/FeedbackForm";
import { getProperty } from "@/lib/data";
import { TOPICS, type Topic } from "@/lib/feedback";
import { addressLine } from "@/lib/format";

export const metadata: Metadata = { title: "Feedback" };

type Search = { searchParams: Promise<{ pin?: string; q?: string; topic?: string }> };

// /feedback (general), /feedback?pin=... (about one property), /feedback?q=...&topic=not_found (a search
// that found nothing). What the visitor typed in the search box is filled in when we know it.
export default async function FeedbackPage({ searchParams }: Search) {
  const { pin, q, topic } = await searchParams;
  const p = pin ? await getProperty(pin) : null;
  const property = p ? { pin: p.pin, address: addressLine(p.address, p.unit) } : null;
  const initialTopic: Topic = topic && topic in TOPICS ? (topic as Topic) : property ? "property_data" : q ? "not_found" : "idea";
  return (
    <section className="card" style={{ maxWidth: 680 }}>
      <header>
        <span className="eyebrow">Feedback</span>
        <h1 style={{ fontSize: "clamp(28px, 4vw, 40px)" }}>
          {property ? "Tell us about this property" : "Tell us what you think"}
        </h1>
        <p className="muted">
          Wrong numbers, a property you couldn&apos;t find, something confusing, or an idea: it all helps.
          {property && <> Your note will be about <Link href={`/p/${property.pin}`}>{property.address}</Link>.</>}
        </p>
      </header>
      <FeedbackForm property={property} query={q ?? null} initialTopic={initialTopic} topics={TOPICS} />
    </section>
  );
}
