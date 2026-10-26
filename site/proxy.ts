// Owner accounts (sign-in, /account, document uploads) are off unless OWNER_ACCOUNTS=on. While off,
// every page and API route behind them answers 404, so none of it is reachable on the public site.
import { type NextRequest, NextResponse } from "next/server";
import { auth, ownerAccountsEnabled } from "@/lib/auth/server";

const enabled = ownerAccountsEnabled();
const requireSession = auth.middleware({ loginUrl: "/auth/sign-in" });

export default function proxy(request: NextRequest) {
  if (!enabled) return NextResponse.rewrite(new URL("/_owner-accounts-off", request.url));   // renders the 404 page
  if (request.nextUrl.pathname.startsWith("/account")) return requireSession(request);
  return NextResponse.next();
}

export const config = {
  matcher: ["/account/:path*", "/auth/:path*", "/api/auth/:path*", "/api/files/:path*"],
};
