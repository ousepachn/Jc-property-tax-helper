// The per-property feedback link at the end of both steps.
import Link from "next/link";

export default function PropertyFeedback({ pin }: { pin: string }) {
  return (
    <p className="muted small">
      Something wrong or missing for this property?{" "}
      <Link href={`/feedback?pin=${encodeURIComponent(pin)}`}>Tell us →</Link>
    </p>
  );
}
