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


      <section className="card" aria-labelledby="h-faq">
        <header><span className="eyebrow">Common questions</span><h2 id="h-faq">Questions owners ask</h2></header>
        <div className="faq">
          <details open>
            <summary>My tax went up because the tax rate rose. Can I appeal the rate?</summary>
            <div className="prose">
              <p>No. An appeal can only change your <b>assessment</b>, which sets your share of the total. The rate is set each
                year by dividing what the city, the schools and the county need to raise by the total assessed value of all
                property in Jersey City. It is the same for every property, so there is nothing about your home to appeal.</p>
              <p>Jersey City&apos;s rate went from <b>$1.604 per $100</b> of assessed value in 2021 to <b>$2.657</b> in 2026, a 66% rise
                that every property paid.</p>
            </div>
          </details>
          <details open>
            <summary>How much of my increase came from the rate, and how much from my assessment?</summary>
            <div className="prose">
              <p>Split the change in two. Example: a home assessed at $500,000 in 2021 and $600,000 in 2026 (an illustration,
                using Jersey City&apos;s actual tax rates).</p>
              <div className="split">
                <div><span>2021 tax: $500,000 assessment × 1.604%</span><span className="num">$8,020</span></div>
                <div><span>2026 tax: $600,000 assessment × 2.657%</span><span className="num">$15,942</span></div>
                <div className="tot"><span>Increase</span><span className="num">$7,922</span></div>
                <div><span><b>From the rate:</b> the 2021 assessment at the 2026 rate, $500,000 × (2.657% − 1.604%)</span><span className="num">$5,265</span></div>
                <div><span><b>From the assessment:</b> $100,000 higher, × the 2026 rate of 2.657%</span><span className="num">$2,657</span></div>
              </div>
              <p>The <b>$5,265 from the rate can&apos;t be appealed.</b> The <b>$2,657 from the assessment can</b>, if the assessment is
                above the allowed range for what the home was worth. An assessment usually rises after a renovation (an added
                assessment) or a citywide revaluation. The appeal check on each property page tells you whether it looks too high.</p>
              <p className="small muted">To do this for your home, take your assessment and tax for two years from your bills or the
                county records search. The tax rate is your tax divided by your assessment.</p>
            </div>
          </details>
          <details>
            <summary>If I can&apos;t appeal the rate, what can I do about it?</summary>
            <div className="prose">
              <ul>
                <li><b>Speak at budget hearings.</b> The rate follows the budgets. The City Council adopts the municipal budget, the
                  Board of Education the school budget, and the Hudson County Board of Commissioners the county budget, each at public
                  meetings where residents can comment.</li>
                <li><b>Read your bill.</b> It shows how your tax splits between the municipal, school and county levies, so you can see
                  which budget drove the change.</li>
                <li><b>Apply for relief you qualify for.</b> New Jersey runs <a href="https://www.nj.gov/treasury/taxation/anchor/index.shtml" target="_blank" rel="noopener">ANCHOR</a>
                  (for homeowners and renters), <a href="https://www.nj.gov/treasury/taxation/staynj/index.shtml" target="_blank" rel="noopener">Stay NJ</a> (age 65 and over) and the
                  <a href="https://www.nj.gov/treasury/taxation/ptr/index.shtml" target="_blank" rel="noopener">Senior Freeze</a>. Senior, disabled and veteran
                  deductions are applied on the bill; ask the Tax Assessor. <a href="https://www.nj.gov/treasury/taxation/relief.shtml" target="_blank" rel="noopener">All state programs</a>.</li>
              </ul>
            </div>
          </details>
          <details>
            <summary>My assessment hasn&apos;t changed in years. Can I still appeal it?</summary>
            <div className="prose">
              <p>Yes, but only in the yearly filing window. Each year&apos;s assessment counts as new, even when the number is the same,
                so it never gets locked in. You appeal the <b>coming</b> year&apos;s assessment after the notice arrives (by February 1)
                and before <b>April 1</b> (or 45 days after the notices are mailed, if that is later). After the deadline, that
                year can&apos;t be appealed; the next chance is the following year.</p>
              <p><b>Example:</b> a home has been assessed at $600,000 since 2024. In October 2026 it is too late to appeal 2026 (the
                deadline was April 1, 2026). The owner can appeal the 2027 assessment by April 1, 2027, arguing what the home was
                worth on October 1, 2026.</p>
              <ul>
                <li><b>After a successful appeal</b>, the board&apos;s judgment usually freezes the assessment for the next two years
                  (the Freeze Act): the assessor can&apos;t raise it unless you add improvements or the city revalues everything. You can
                  still appeal during those years, and the freeze ends after the second.</li>
                <li><b>Added or omitted assessment bills</b> (see the next question) have their own deadline: December 1 of the year
                  you are billed.</li>
                <li><b>A factual mistake</b> on your property record, like the wrong floor area or room count, can be raised with the
                  Tax Assessor at any time.</li>
              </ul>
            </div>
          </details>
          <details>
            <summary>I renovated. When will my taxes change, and will I get a back bill?</summary>
            <div className="prose">
              <p>Once the work is finished, the assessor adds its value with an <b>added assessment</b>, billed for the whole months
                after completion. When the bill comes depends on when the work finished:</p>
              <ul>
                <li><b>Finished January 1 to September 30:</b> billed in the fall of the same year, for the rest of that year.</li>
                <li><b>Finished October 1 to December 31:</b> billed in the fall of the <b>following</b> year, for the rest of the
                  completion year plus the whole following year (that year&apos;s assessment was set on October 1, before the work was done).</li>
                <li>From then on, the work is part of your regular assessment.</li>
                <li>If the assessor misses it, an <b>omitted added assessment</b> can be billed later, but only one year back.</li>
              </ul>
              <p><b>Example:</b> work finished in November 2025, and the assessor adds $50,000 of assessed value (an illustration;
                the real amount depends on the work).</p>
              <div className="split">
                <div><span>December 2025 (1 month): $50,000 × 2.335% ÷ 12</span><span className="num">$97</span></div>
                <div><span>All of 2026: $50,000 × 2.657%</span><span className="num">$1,329</span></div>
                <div className="tot"><span>Added assessment bill, fall 2026</span><span className="num">$1,426</span></div>
                <div><span>2027 onward: in the regular assessment, at the year&apos;s rate</span><span className="num">about $1,329 a year</span></div>
              </div>
              <p>If that bill isn&apos;t sent until fall 2027, it can cover only 2026; the December 2025 month can no longer be billed.
                Seeing nothing during the year after the work is normal. Set the money aside, appeal the added assessment by December 1
                if it looks too high, or ask the Tax Assessor whether one is pending.</p>
            </div>
          </details>
          <details>
            <summary>Will a successful appeal lower my future bills too?</summary>
            <div className="prose">
              <p>Usually yes. A county board judgment generally holds for the next two years as well (the Freeze Act), unless the city
                revalues all properties. Your tax still moves with the rate each year.</p>
            </div>
          </details>
        </div>
      </section>

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
