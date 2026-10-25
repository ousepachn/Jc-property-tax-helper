import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "How to appeal" };

const DATES: [string, string, string][] = [
  ["2026-10-01", "Valuation date", "Your appeal is about what your property was worth on this day."],
  ["2027-02-01", "Assessment notice arrives; first-quarter tax due",
    "Check the 2027 assessment on the postcard. Taxes through the first quarter of 2027 must be paid for the board to hear your appeal."],
  ["2027-04-01", "Deadline to file",
    "Your petition must be received by the Hudson County Board of Taxation by April 1, 2027. A postmark is not enough."],
  ["2027-05-01", "Hearings, usually in spring",
    "Send your evidence to the board, the Tax Assessor and the City Clerk at least 7 days before your hearing."],
  ["2027-07-01", "Decision, by about July 1",
    "If you disagree with the decision, you have 45 days to appeal to the New Jersey Tax Court."],
];

const FEES = [
  ["Under $150,000", "$5"],
  ["$150,000 to $499,999", "$25"],
  ["$500,000 to $999,999", "$100"],
  ["$1,000,000 or more", "$150"],
];

export default function AppealGuide() {
  const today = new Date();
  return (
    <>
      <section className="prose">
        <span className="eyebrow">Guide</span>
        <h1>How to appeal your property tax assessment</h1>
        <p className="muted" style={{ fontSize: 18 }}>
          You can&apos;t appeal your tax bill itself. You appeal your <b>assessment</b>, the value the city puts on your
          property. If you show it is too high for what your property was worth, the board lowers it, and your tax goes
          down with it.
        </p>
      </section>

      <section className="card" aria-labelledby="h-test">
        <header><span className="eyebrow">The rule</span><h2 id="h-test">When an appeal can work</h2></header>
        <div className="prose">
          <p>
            New Jersey doesn&apos;t expect assessments to equal market value. Each year the state sets a range for each town.
            For 2027 in Jersey City, an assessment is left alone if it is between <b>56.69% and 76.69%</b> of what the
            property was worth on October 1, 2026 (the city average is 66.69%).
          </p>
          <ul>
            <li><b>Above 76.69%:</b> the board resets your assessment to your value × 66.69%. This is when an appeal helps.</li>
            <li><b>Between 56.69% and 76.69%:</b> the board leaves it as it is.</li>
            <li><b>Below 56.69%:</b> the board can <b>raise</b> it. Check before you file.</li>
          </ul>
          <p className="small muted">
            Example: assessed at $600,000. If you show the home was worth $700,000, that&apos;s 85.7%, above the limit, so
            the board would set it to about $466,800. Our appeal check on each property page does this math for you.
          </p>
        </div>
      </section>

      <section className="card" aria-labelledby="h-dates">
        <header><span className="eyebrow">Key dates</span><h2 id="h-dates">Appealing your 2027 assessment</h2></header>
        <ol className="timeline">
          {DATES.map(([iso, title, help]) => {
            const d = new Date(iso + "T12:00:00");
            const past = d < today;
            return (
              <li key={iso} className={past ? "past" : ""}>
                <span className="when">{d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}</span>
                <span><b>{title}</b>{past ? " · passed" : ""}<br /><span className="small muted">{help}</span></span>
              </li>
            );
          })}
        </ol>
      </section>

      <section className="card" aria-labelledby="h-steps">
        <header><span className="eyebrow">Step by step</span><h2 id="h-steps">What to do</h2></header>
        <ol className="prose" style={{ paddingLeft: 22 }}>
          <li>
            <b>Check your score and the comparable sales.</b> Look up your property on this site. If the appeal check says
            &quot;unlikely&quot;, an appeal probably won&apos;t help.
          </li>
          <li>
            <b>Get your property record card.</b> Email the Tax Assessor and ask for it (an OPRA request works). It lists
            your size, rooms, bathrooms and condition as the city has them. Mistakes there are the easiest thing to fix.
          </li>
          <li>
            <b>Pick 3 to 5 comparable sales.</b> Normal market sales of similar properties near you, sold close to
            October 1, 2026. Write down each one&apos;s block, lot, price and sale date, and confirm them on the{" "}
            <a href="https://taxrecords-nj.com/pub/cgi/prc6.cgi?&ms_user=ctb09&passwd=&srch_type=0&adv=0&out_type=0&district=0906" target="_blank" rel="noopener">
              county&apos;s records search
            </a>. Other homes&apos; assessments don&apos;t count as evidence; sales do.
          </li>
          <li>
            <b>Document anything that lowers your value.</b> Dated photos and repair estimates for problems like a failing
            roof or water damage. An appraisal is strong evidence, but the appraiser has to attend your hearing.
          </li>
          <li><b>Pay your taxes through the first quarter of 2027.</b> The board won&apos;t hear your appeal otherwise.</li>
          <li>
            <b>File by April 1, 2027.</b> File online at{" "}
            <a href="https://secure.njappealonline.com/prodappeals/login.aspx" target="_blank" rel="noopener">NJ Online Assessment Appeals</a>{" "}
            (it notifies the assessor and clerk for you), or on paper with{" "}
            <a href="https://www.nj.gov/treasury/taxation/pdf/other_forms/lpt/petappl.pdf" target="_blank" rel="noopener">Form A-1</a>.
            If your assessment is over $1 million, you can file directly with the Tax Court instead.
          </li>
          <li>
            <b>Send your evidence 7 days before the hearing</b> to the board, the Tax Assessor and the City Clerk. You can
            usually choose an in-person, virtual or written-only hearing.
          </li>
        </ol>
      </section>

      <div className="grid2">
        <section className="card" aria-labelledby="h-fees">
          <header><span className="eyebrow">Filing fee</span><h2 id="h-fees">Based on your assessment</h2></header>
          <table>
            <tbody>
              {FEES.map(([band, fee]) => <tr key={band}><td>{band}</td><td className="r">{fee}</td></tr>)}
            </tbody>
          </table>
        </section>
        <section className="card" aria-labelledby="h-after">
          <header><span className="eyebrow">After the decision</span><h2 id="h-after">What happens next</h2></header>
          <div className="prose small">
            <p>If you win, the new assessment usually holds for the next two years too (the &quot;Freeze Act&quot;), unless the city does a revaluation.</p>
            <p>If you disagree, you have 45 days to appeal to the New Jersey Tax Court.</p>
            <p>Many owners hire a tax appeal attorney, who usually charges a share of the savings. You can also file yourself.</p>
          </div>
        </section>
      </div>

      <section className="card" aria-labelledby="h-contacts">
        <header><span className="eyebrow">Contacts</span><h2 id="h-contacts">Who to contact</h2></header>
        <div className="contacts">
          <div className="note">
            <b>Jersey City Tax Assessor</b>
            <span>One Jackson Square (364 MLK Drive), 3rd floor, Jersey City, NJ 07305</span>
            <span>201-547-5131 · jccityassessor@jcnj.org</span>
          </div>
          <div className="note">
            <b>Hudson County Board of Taxation</b>
            <span>257 Cornelison Ave, 3rd floor, Jersey City, NJ 07302</span>
            <span>201-395-6260</span>
            <a href="https://www.hcnj.us/finance/tax-assessments/board-of-taxation/" target="_blank" rel="noopener">Board website</a>
          </div>
          <div className="note">
            <b>Official sources</b>
            <a href="https://www.nj.gov/treasury/taxation/pdf/lpt/chap123/2027CH123.pdf" target="_blank" rel="noopener">2027 ratios for every town (PDF)</a>
            <a href="https://www.nj.gov/treasury/taxation/pdf/other_forms/lpt/petappl.pdf" target="_blank" rel="noopener">Form A-1 and instructions (PDF)</a>
          </div>
        </div>
      </section>
      <p><Link href="/">← Look up a property</Link></p>
    </>
  );
}
