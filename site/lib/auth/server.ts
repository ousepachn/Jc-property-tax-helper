// Neon Auth (managed Better Auth). Sessions live in signed cookies on this site's domain; the
// /api/auth route proxies sign-up, sign-in and sign-out to the project's Neon Auth service.
import { createNeonAuth } from "@neondatabase/auth/next/server";

export const auth = createNeonAuth({
  baseUrl: process.env.NEON_AUTH_BASE_URL!,
  cookies: { secret: process.env.NEON_AUTH_COOKIE_SECRET! },
});
