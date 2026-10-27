// Title block shared by a property's two steps: the overview and the appeal check.
import Link from "next/link";
import { addressLine, kindLabel, money, sqft } from "@/lib/format";
import type { Property } from "@/lib/types";

export default function PropertyHeader({ p, step }: { p: Property; step: 1 | 2 }) {
  const latestYear = Math.max(...Object.keys(p.assessment).map(Number));
  return (
    <div className="prop-head">
      <Link href="/" className="back">← Search another address</Link>
      <nav className="steps" aria-label="Steps">
        <Link href={`/p/${p.pin}`} aria-current={step === 1 ? "page" : undefined}><span className="n">1</span>Overview</Link>
        <Link href={`/p/${p.pin}/appeal`} aria-current={step === 2 ? "page" : undefined}><span className="n">2</span>Appeal &amp; permits</Link>
      </nav>
      <h1>{addressLine(p.address, p.unit)}</h1>
      <div className="facts">
        <span><b>{kindLabel(p.kind)}</b></span>
        {p.sq_ft ? <span><b>{sqft(p.sq_ft)}</b></span> : null}
        {p.year_built ? <span>Built <b>{p.year_built}</b></span> : null}
        {Number.isFinite(latestYear) && <span>{latestYear} assessment <b>{money(p.assessment[latestYear])}</b></span>}
        <span className="small">Block/lot {p.pin.split("_").slice(1).join(" / ")}</span>
      </div>
    </div>
  );
}
