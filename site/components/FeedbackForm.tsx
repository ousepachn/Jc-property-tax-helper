"use client";

import { useEffect, useState } from "react";

interface Props {
  property: { pin: string; address: string } | null;
  query: string | null;
  initialTopic: string;
  topics: Record<string, string>;
}

const PLACEHOLDER: Record<string, string> = {
  property_data: "What looks wrong? For example: the square footage should be 1,150, or the tax shown doesn't match my bill.",
  not_found: "What address or unit were you looking for?",
  idea: "What would make this more useful for you?",
  other: "What's on your mind?",
};

export default function FeedbackForm({ property, query, initialTopic, topics }: Props) {
  const [topic, setTopic] = useState(initialTopic);
  const [message, setMessage] = useState("");
  const [email, setEmail] = useState("");
  const [searched, setSearched] = useState(query ?? "");
  const [state, setState] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [error, setError] = useState("");

  // what they last typed in the search box (Search.tsx keeps it for this tab)
  useEffect(() => {
    if (query) return;
    try {
      const last = sessionStorage.getItem("lastSearch");
      if (last) setSearched(last);
    } catch {}
  }, [query]);

  if (state === "sent") {
    return (
      <div className="verdict good" role="status">
        <span className="pill">Thank you</span>
        <p>We read every message.{email ? " If we have a question we'll write to you." : ""}</p>
      </div>
    );
  }

  return (
    <form
      className="form"
      onSubmit={async (e) => {
        e.preventDefault();
        setState("sending");
        setError("");
        const website = (e.currentTarget.elements.namedItem("website") as HTMLInputElement).value;
        try {
          const r = await fetch("/api/feedback", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ topic, message, email, website, pin: property?.pin, query: searched,
              page: document.referrer ? new URL(document.referrer).pathname : null }),
          });
          const j = await r.json().catch(() => ({}));
          if (!r.ok) throw new Error(j.error || "Something went wrong. Please try again.");
          setState("sent");
        } catch (err) {
          setError((err as Error).message);
          setState("error");
        }
      }}
    >
      {property && (
        <div className="note small">
          <b>Property:</b> {property.address} · Block/lot {property.pin.split("_").slice(1).join(" / ")}
        </div>
      )}
      <label>
        What is it about?
        <select value={topic} onChange={(e) => setTopic(e.target.value)}>
          {Object.entries(topics).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </label>
      <label>
        <span>What you searched for <span className="muted small" style={{ fontWeight: 400 }}>(optional)</span></span>
        <input value={searched} onChange={(e) => setSearched(e.target.value)} maxLength={120} placeholder="e.g. 77 Hudson St 1205" />
      </label>
      <label>
        Your message
        <textarea required minLength={3} maxLength={2000} rows={6} value={message}
          onChange={(e) => setMessage(e.target.value)} placeholder={PLACEHOLDER[topic]} />
      </label>
      <label>
        <span>Email <span className="muted small" style={{ fontWeight: 400 }}>(optional, only if you&apos;d like a reply)</span></span>
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} maxLength={200} autoComplete="email" />
      </label>
      {/* honeypot: hidden from people, filled in by bots */}
      <input name="website" tabIndex={-1} autoComplete="off" aria-hidden="true" style={{ position: "absolute", left: -9999 }} />
      {error && <p className="note" role="alert">{error}</p>}
      <button type="submit" className="cta" disabled={state === "sending"}>{state === "sending" ? "Sending…" : "Send feedback"}</button>
      <p className="small muted">
        We store your message, the property and search above, and your email if you give one, only to improve this
        site. We don&apos;t share them.
      </p>
    </form>
  );
}
