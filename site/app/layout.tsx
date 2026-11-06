import type { Metadata, Viewport } from "next";
import { Libre_Franklin, Source_Serif_4 } from "next/font/google";
import Link from "next/link";
import { Analytics } from "@vercel/analytics/next";
import { SpeedInsights } from "@vercel/speed-insights/next";
import "./globals.css";

// Editorial pairing: a serif for headlines and prose, a Franklin-style sans for figures and interface.
const sans = Libre_Franklin({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
const serif = Source_Serif_4({ subsets: ["latin"], variable: "--font-serif", display: "swap" });

export const metadata: Metadata = {
  title: { default: "Jersey City Tax Check", template: "%s · Jersey City Tax Check" },
  description:
    "See how your Jersey City property tax has changed, how it compares with similar homes, and whether an appeal could help.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, viewportFit: "cover" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${serif.variable}`}>
      <body>
        <header className="top">
          <div className="wrap">
            <div className="topline">
              <span>Property tax, from public records</span>
              <nav className="nav" aria-label="Main">
                <Link href="/appeal">Appeal guide</Link>
                <Link href="/feedback">Feedback</Link>
                {process.env.OWNER_ACCOUNTS === "on" && <Link href="/account">Owner sign-in</Link>}
              </nav>
            </div>
            <div className="masthead">
              <Link href="/" className="brand">Jersey City Tax Check</Link>
            </div>
          </div>
        </header>
        <main className="wrap">{children}</main>
        <footer>
          <div className="wrap">
            <p>
              Built from public records: Jersey City&apos;s tax bills and permit portal, the Hudson County Board of
              Taxation&apos;s assessments and the State of New Jersey&apos;s parcel map.
            </p>
            <p>
              An independent tool, not a government site. Not legal or tax advice; confirm figures with the Tax Assessor.
            </p>
            <p>
              Something wrong or missing? <Link href="/feedback">Send feedback</Link>.
            </p>
          </div>
        </footer>
        <Analytics />
        <SpeedInsights />
      </body>
    </html>
  );
}
