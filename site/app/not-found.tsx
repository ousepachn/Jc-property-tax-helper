import Link from "next/link";

export default function NotFound() {
  return (
    <section className="card">
      <h1>Property not found</h1>
      <p className="muted">We couldn&apos;t find that property. It may have been merged or renumbered.</p>
      <p><Link href="/">Search by address →</Link></p>
    </section>
  );
}
