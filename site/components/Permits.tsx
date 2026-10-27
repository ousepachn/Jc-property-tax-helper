// Construction permits on a property and what they may mean for its tax: a short alert for the
// overview, and the full history with the added-assessment explainer for the appeal step.
import Link from "next/link";
import TaxImpact from "./TaxImpact";
import { isoDate, PERMIT_CATEGORY, RELEVANCE } from "@/lib/format";
import type { Meta, Permits } from "@/lib/types";

function outlook(p: Permits) {
  const o = p.outlook;
  if (!o) return null;
  const permit = p.list.find((x) => x.no === o.permit);
  const what = permit?.description ? `“${permit.description.toLowerCase()}”` : `permit ${o.permit}`;
  if (o.state === "in_progress")
    return { tone: "warn", title: "Open permit: an added assessment may follow",
      body: `Work under ${what} isn't finished yet. When it is, the Tax Assessor usually adds the value of the work to your assessment, and your tax goes up with it.` };
  if (o.state === "may_be_added")
    return { tone: "warn", title: "An added assessment may still come",
      body: `Work under ${what} was finished in ${o.year}, and your bills don't show an added assessment since. One can still arrive, usually in the fall.` };
  return { tone: "calm", title: "Recent work is already on your bill",
    body: `Your bills show an added assessment after work under ${what} (${o.year}), so that work is likely already in your assessment.` };
}

export function PermitAlert({ permits, pin }: { permits?: Permits; pin: string }) {
  const o = permits && outlook(permits);
  if (!o) return null;
  return (
    <div className={`alert${o.tone === "calm" ? " calm" : ""}`} role="note">
      <span className="ico" aria-hidden="true">!</span>
      <b>{o.title}</b>
      <span>
        {o.body} <Link href={`/p/${pin}/appeal#permits`}>Permits and what they could cost →</Link>
      </span>
    </div>
  );
}

export function PermitHistory({ permits, meta }: { permits?: Permits; meta: Meta }) {
  const rate = meta.rate?.[String(meta.last_year)];
  const o = permits && outlook(permits);
  return (
    <section className="card" id="permits" aria-labelledby="h-permits">
      <header>
        <span className="eyebrow">Permits and construction</span>
        <h2 id="h-permits">Work on this property since 2015</h2>
        <p className="muted small">From Jersey City&apos;s permit portal. Repairs and equipment swaps rarely change an assessment; new space, new units and major renovations usually do.</p>
      </header>
      {!meta.permits || !permits ? (
        <p className="muted">Permit history for this property isn&apos;t loaded yet. Check back soon.</p>
      ) : (
        <>
          {o && (
            <div className={`alert${o.tone === "calm" ? " calm" : ""}`} role="note">
              <span className="ico" aria-hidden="true">!</span>
              <b>{o.title}</b>
              <span>{o.body}</span>
            </div>
          )}
          {permits.list.length ? (
            <ul className="permits">
              {permits.list.map((x) => (
                <li key={x.no}>
                  <span className="when">{isoDate(x.issued ?? x.applied)}</span>
                  <span className="what">
                    <b>{x.description ?? PERMIT_CATEGORY[x.category] ?? x.type}</b>
                    <span className="small muted">
                      {PERMIT_CATEGORY[x.category] ?? x.type} · {x.no} · {x.status}
                      {x.finished ? `, finished ${isoDate(x.finished)}` : ""}
                      {x.building ? " · whole building" : ""}
                    </span>
                  </span>
                  <span className={`chip ${x.relevance}`}>{RELEVANCE[x.relevance]}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">No permits on record since 2015.</p>
          )}
          {permits.building_count > 0 && (
            <p className="small muted">Includes {permits.building_count} permit{permits.building_count > 1 ? "s" : ""} for the whole building.</p>
          )}
        </>
      )}
      <details className="faq">
        <summary>How renovations reach your tax bill</summary>
        <div className="prose">
          <p>
            When work raises a property&apos;s value, New Jersey assessors add it to the tax roll as an <b>added
            assessment</b>: a separate bill, usually mailed in the fall, for the months of the year after the work was
            finished. From the next year on, the higher value is part of your regular assessment.
          </p>
          <p>
            You can appeal an added assessment too. The deadline is usually December 1 of the year it&apos;s billed;
            check the date on the bill. Before a big project, ask the Tax Assessor whether an improvement exemption
            applies: applications have short deadlines.
          </p>
        </div>
      </details>
      {rate && meta.ratio && (
        <div className="grid-gap">
          <h3>What could finished work add?</h3>
          <TaxImpact ratio={meta.ratio.avg} rate={rate} year={meta.last_year} />
        </div>
      )}
    </section>
  );
}
