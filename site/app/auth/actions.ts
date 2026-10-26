"use server";

import { notFound, redirect } from "next/navigation";
import { auth, ownerAccountsEnabled } from "@/lib/auth/server";

function field(form: FormData, name: string) {
  return String(form.get(name) ?? "").trim();
}

function back(mode: string, message: string): never {
  redirect(`/auth/sign-in?mode=${mode}&error=${encodeURIComponent(message)}`);
}

export async function signIn(form: FormData) {
  if (!ownerAccountsEnabled()) notFound();
  const { error } = await auth.signIn.email({ email: field(form, "email"), password: String(form.get("password") ?? "") });
  if (error) back("sign-in", error.message || "Those details didn't match an account.");
  redirect("/account");
}

export async function signUp(form: FormData) {
  if (!ownerAccountsEnabled()) notFound();
  const email = field(form, "email");
  const { error } = await auth.signUp.email({
    email,
    password: String(form.get("password") ?? ""),
    name: field(form, "name") || email,
  });
  if (error) back("sign-up", error.message || "Couldn't create the account.");
  redirect("/account");
}

export async function signOut() {
  if (!ownerAccountsEnabled()) notFound();
  await auth.signOut();
  redirect("/");
}
