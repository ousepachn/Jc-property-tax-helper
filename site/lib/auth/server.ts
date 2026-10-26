// Neon Auth (managed Better Auth). Sessions live in signed cookies on this site's domain; the
// /api/auth route proxies sign-up, sign-in and sign-out to the project's Neon Auth service.
import { createNeonAuth } from "@neondatabase/auth/next/server";

export const auth = createNeonAuth({
  baseUrl: process.env.NEON_AUTH_BASE_URL!,
  cookies: { secret: process.env.NEON_AUTH_COOKIE_SECRET! },
});

// Owner accounts are off unless OWNER_ACCOUNTS=on (see proxy.ts). Checked again inside every action and
// route, because server actions can be called from any URL, not only the ones proxy.ts covers.
export function ownerAccountsEnabled() {
  return process.env.OWNER_ACCOUNTS === "on";
}
