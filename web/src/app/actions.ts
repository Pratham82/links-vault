"use server";

// Server actions: the browser calls these like functions, Next.js runs them on the server
// (where API_KEY lives) and re-renders the page with fresh data in the same round trip.
// Anyone who can reach the dashboard can call them, so every input is validated here.

import { refresh } from "next/cache";

import { ApiError, deleteLink, updateLink } from "@/lib/api";
import { parseTagInput } from "@/lib/format";
import { CONTENT_TYPES, type ContentType } from "@/lib/types";

export interface ActionResult {
  ok: boolean;
  error?: string;
}

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
