import { auth, ownerAccountsEnabled } from "@/lib/auth/server";

const handlers = auth.handler();
const off = () => new Response(null, { status: 404 });
type Handler = (typeof handlers)["GET"];
const guard = (h: Handler): Handler => (req, ctx) => (ownerAccountsEnabled() ? h(req, ctx) : Promise.resolve(off()));

export const GET = guard(handlers.GET);
export const POST = guard(handlers.POST);
export const PUT = guard(handlers.PUT);
export const DELETE = guard(handlers.DELETE);
export const PATCH = guard(handlers.PATCH);
