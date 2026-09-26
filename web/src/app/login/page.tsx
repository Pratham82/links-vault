import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { LoginForm } from "@/components/LoginForm";
import { isSignedIn, signInConfigured } from "@/lib/session";

export const metadata: Metadata = { title: "Sign in · Link Vault" };

export default async function LoginPage() {
  if (await isSignedIn()) redirect("/");

  return (
    <div className="mx-auto flex max-w-sm flex-col gap-4 rounded-xl border bg-card p-6 shadow-xs">
      <div>
        <h1 className="font-heading text-lg font-semibold">Sign in</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Signing in lets you edit and delete links.
        </p>
      </div>
      {signInConfigured() ? (
        <LoginForm />
      ) : (
        <p className="text-sm text-destructive">
          Sign-in is off. Set <code>DASHBOARD_PASSWORD</code> in the dashboard&apos;s environment
          and restart it.
        </p>
      )}
    </div>
  );
}
