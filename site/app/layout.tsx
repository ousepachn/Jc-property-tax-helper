import type { Metadata, Viewport } from "next";
import { Public_Sans } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const publicSans = Public_Sans({ subsets: ["latin"], variable: "--font-public-sans", display: "swap" });

export const metadata: Metadata = {
  title: { default: "Jersey City Tax Check", template: "%s · Jersey City Tax Check" },
  description:
    "See how your Jersey City property tax has changed, how it compares with similar homes, and whether an appeal could help.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, viewportFit: "cover" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={publicSans.variable}>
      <body>
        <div className="top">
          <div className="wrap">
            <Link href="/" className="brand">
              <span className="mark" aria-hidden="true">$</span>
              Jersey City Tax Check
            </Link>
            <nav className="nav" aria-label="Main">
              <Link href="/">Map &amp; search</Link>
              <Link href="/appeal">How to appeal</Link>
              {process.env.OWNER_ACCOUNTS === "on" && <Link href="/account">Owner sign-in</Link>}
            </nav>
          </div>
        </div>
        <main className="wrap">{children}</main>
        <footer>
          <div className="wrap">
            <p>
              Built from public records: the Jersey City tax bill site, the Hudson County Board of Taxation&apos;s
              assessment records and the State of New Jersey&apos;s parcel map and tax lists.
            </p>
            <p>
              This is an independent tool, not a government site. The appeal check is a rough screen, not legal or
              tax advice. Always confirm figures with the Tax Assessor.
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
