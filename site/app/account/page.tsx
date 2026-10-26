import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { auth } from "@/lib/auth/server";
import { displayName, files, ownerPrefix } from "@/lib/storage";
import { signOut } from "../auth/actions";

export const metadata: Metadata = { title: "Your account" };
export const dynamic = "force-dynamic";

export default async function AccountPage({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { data: session } = await auth.getSession();
  if (!session?.user) redirect("/auth/sign-in");
  const { error } = await searchParams;
  const { items } = await files.list({ prefix: ownerPrefix(session.user.id) });
  items.sort((a, b) => (b.lastModified ?? 0) - (a.lastModified ?? 0));

  return (
    <section className="card">
      <div>
        <div className="eyebrow">Your account</div>
        <h1>Signed in as {session.user.email}</h1>
      </div>
      <div className="grid-gap">
        <h2>Your documents</h2>
        <p className="muted small">
          Keep photos, an appraisal or other appeal evidence here. Only you can see them. Up to 4 MB each.
        </p>
        {error && <p className="note" role="alert">{error}</p>}
        {items.length ? (
          <ul className="filelist">
            {items.map((f) => (
              <li key={f.key}>
                <a href={`/api/files/download?key=${encodeURIComponent(f.key)}`}>{displayName(f.key)}</a>
                <span className="small muted num">{Math.max(1, Math.round(f.size / 1024))} KB</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="small muted">No documents yet.</p>
        )}
        <form action="/api/files" method="post" encType="multipart/form-data" className="form row">
          <input type="file" name="file" required />
          <button type="submit" className="cta">Upload</button>
        </form>
      </div>
      <form action={signOut}>
        <button type="submit" className="linkbtn">Sign out</button>
      </form>
    </section>
  );
}
