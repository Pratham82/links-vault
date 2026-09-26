"use client";

import { LoaderCircle } from "lucide-react";
import { useActionState } from "react";

import { signIn, type ActionResult } from "@/app/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const IDLE: ActionResult = { ok: false };

export function LoginForm() {
  const [result, formAction, pending] = useActionState(signIn, IDLE);

  return (
    <form action={formAction} className="flex flex-col gap-3">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="password" className="text-xs font-medium text-muted-foreground">
          Password
        </Label>
        <Input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          autoFocus
          aria-invalid={result.error ? true : undefined}
        />
      </div>
      {result.error && <p className="text-xs text-destructive">{result.error}</p>}
      <Button type="submit" disabled={pending}>
        {pending && <LoaderCircle data-icon="inline-start" className="animate-spin" />}
        {pending ? "Signing in…" : "Sign in"}
      </Button>
    </form>
  );
}
