// Upload one of the signed-in owner's documents to Object Storage.
import { NextResponse } from "next/server";
import { auth, ownerAccountsEnabled } from "@/lib/auth/server";
import { files, MAX_UPLOAD_BYTES, ownerKey } from "@/lib/storage";

export async function POST(request: Request) {
  if (!ownerAccountsEnabled()) return NextResponse.json({ error: "Not found" }, { status: 404 });
  const { data: session } = await auth.getSession();
  if (!session?.user) return NextResponse.json({ error: "Sign in first" }, { status: 401 });
  const back = (error?: string) =>
    NextResponse.redirect(new URL(error ? `/account?error=${encodeURIComponent(error)}` : "/account", request.url), 303);

  const file = (await request.formData()).get("file");
  if (!(file instanceof File) || file.size === 0) return back("Choose a file to upload.");
  if (file.size > MAX_UPLOAD_BYTES) return back("That file is over 4 MB.");
  await files.upload(ownerKey(session.user.id, file.name), file, {
    contentType: file.type || "application/octet-stream",
  });
  return back();
}
