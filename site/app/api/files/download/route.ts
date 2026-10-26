// Send the signed-in owner to a short-lived link for one of their own documents.
import { NextResponse } from "next/server";
import { auth } from "@/lib/auth/server";
import { displayName, files, ownerPrefix } from "@/lib/storage";

export async function GET(request: Request) {
  const { data: session } = await auth.getSession();
  if (!session?.user) return NextResponse.json({ error: "Sign in first" }, { status: 401 });
  const key = new URL(request.url).searchParams.get("key") ?? "";
  if (!key.startsWith(ownerPrefix(session.user.id)) || key.includes("..")) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  const url = await files.url(key, {
    expiresIn: 300,
    responseContentDisposition: `attachment; filename="${displayName(key)}"`,
  });
  return NextResponse.redirect(url, 302);
}
