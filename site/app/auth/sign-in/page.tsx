import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ownerAccountsEnabled } from "@/lib/auth/server";
import { signIn, signUp } from "../actions";

export const metadata: Metadata = { title: "Owner sign-in" };

export default async function SignInPage({ searchParams }: { searchParams: Promise<{ mode?: string; error?: string }> }) {
  if (!ownerAccountsEnabled()) notFound();
  const { mode, error } = await searchParams;
  const creating = mode === "sign-up";
  return (
    <section className="card authcard">
      <div>
        <div className="eyebrow">Property owners</div>
        <h1>{creating ? "Create an account" : "Sign in"}</h1>
        <p className="muted small">
          An account lets you keep documents for an appeal in one place. Looking up a property never needs one.
        </p>
      </div>
      {error && <p className="note" role="alert">{error}</p>}
      <form action={creating ? signUp : signIn} className="form">
        {creating && (
          <label>
            Name
            <input name="name" autoComplete="name" />
          </label>
        )}
        <label>
          Email
          <input name="email" type="email" required autoComplete="email" />
        </label>
        <label>
          Password
          <input name="password" type="password" required minLength={8}
            autoComplete={creating ? "new-password" : "current-password"} />
        </label>
        <button type="submit" className="cta">{creating ? "Create account" : "Sign in"}</button>
      </form>
      <p className="small">
        {creating ? (
          <>Already have an account? <Link href="/auth/sign-in">Sign in</Link></>
        ) : (
          <>New here? <Link href="/auth/sign-in?mode=sign-up">Create an account</Link></>
        )}
      </p>
    </section>
  );
}
