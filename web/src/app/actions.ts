"use server";

// Server actions: the browser calls these like functions, Next.js runs them on the server
// (where API_KEY lives) and re-renders the page with fresh data in the same round trip.
// Anyone who can reach the dashboard can call them, so every input is validated here, and
// the ones that change data check for a signed-in session first.

import { refresh } from "next/cache";
import { redirect } from "next/navigation";

import { ApiError, deleteLink, updateLink } from "@/lib/api";
import { parseTagInput } from "@/lib/format";
import {
  endSession,
  isSignedIn,
  passwordMatches,
  signInConfigured,
  startSession,
} from "@/lib/session";
import { CONTENT_TYPES, type ContentType } from "@/lib/types";

export interface ActionResult {
  ok: boolean;
  error?: string;
}

const SIGNED_OUT: ActionResult = { ok: false, error: "Sign in to change links" };

// How long a wrong password waits before answering, to slow down guessing.
const FAILED_SIGN_IN_DELAY_MS = 1000;

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function failure(error: unknown): ActionResult {
  if (error instanceof ApiError) return { ok: false, error: error.message };
  throw error;
}

export async function saveLink(
  linkId: string,
  _previous: ActionResult,
  form: FormData,
): Promise<ActionResult> {
  if (!(await isSignedIn())) return SIGNED_OUT;
  if (!UUID_RE.test(linkId)) return { ok: false, error: "Unknown link" };
  const note = String(form.get("note") ?? "");
  const tags = parseTagInput(String(form.get("tags") ?? ""));
  const type = String(form.get("content_type") ?? "");
  if (!CONTENT_TYPES.includes(type as ContentType)) {
    return { ok: false, error: "Pick a type from the list" };
  }
  try {
    await updateLink(linkId, { note: note.trim() || null, tags, content_type: type as ContentType });
  } catch (error) {
    return failure(error);
  }
  refresh();
  return { ok: true };
}

export async function removeLink(linkId: string): Promise<ActionResult> {
  if (!(await isSignedIn())) return SIGNED_OUT;
  if (!UUID_RE.test(linkId)) return { ok: false, error: "Unknown link" };
  try {
    await deleteLink(linkId);
  } catch (error) {
    // Already gone is what the user wanted anyway.
    if (!(error instanceof ApiError && error.status === 404)) return failure(error);
  }
  refresh();
  return { ok: true };
}

export async function signIn(_previous: ActionResult, form: FormData): Promise<ActionResult> {
  if (!signInConfigured()) {
    return { ok: false, error: "Sign-in isn't set up: set DASHBOARD_PASSWORD for the dashboard" };
  }
  if (!passwordMatches(String(form.get("password") ?? ""))) {
    await new Promise((resolve) => setTimeout(resolve, FAILED_SIGN_IN_DELAY_MS));
    return { ok: false, error: "Wrong password" };
  }
  await startSession();
  // redirect() works by throwing, so it stays outside any try/catch.
  redirect("/");
}

export async function signOut(): Promise<void> {
  await endSession();
  redirect("/login");
}
