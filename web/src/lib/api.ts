// The one place the dashboard talks to the Link Vault API.
//
// `server-only` makes the build fail if a client component ever imports this module, so
// API_KEY can never end up in the browser bundle. Pages call it while rendering on the
// server; client components go through the server actions in app/actions.ts instead.
import "server-only";

import { toApiQuery, type Filters } from "./filters";
import type { Link, LinkPage, LinkUpdate } from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function config(): { baseUrl: string; apiKey: string } {
  const apiKey = process.env.API_KEY;
  if (!apiKey) {
    throw new ApiError(500, "API_KEY is not set for the dashboard");
  }
  // Unset means local development. Set but empty or not a URL is a config mistake (e.g. a
  // blank value in Vercel's settings), so say so instead of failing with a confusing fetch error.
  const raw = process.env.API_BASE_URL ?? "http://localhost:8000";
  const baseUrl = raw.trim().replace(/\/+$/, "");
  if (!URL.canParse(baseUrl) || !/^https?:\/\//.test(baseUrl)) {
    throw new ApiError(
      500,
      `API_BASE_URL must be the API's full URL, like https://links-api.example.com (got "${raw}")`,
    );
  }
  return { baseUrl, apiKey };
}

async function detailOf(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const { detail } = body as { detail: unknown };
      if (typeof detail === "string") return detail;
      // FastAPI's validation errors: [{ msg: "..." }, ...]
      if (Array.isArray(detail)) {
        return detail.map((item: { msg?: string }) => item.msg ?? "").join("; ");
      }
    }
  } catch {
    // Not JSON; fall through.
  }
  return response.statusText || `HTTP ${response.status}`;
}

/** fetch() against the API with the key attached. Throws ApiError on a non-2xx response. */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const { baseUrl, apiKey } = config();
  const headers = new Headers(init.headers);
  headers.set("X-API-Key", apiKey);
  let response: Response;
  try {
    // no-store: the dashboard always shows the database as it is right now.
    response = await fetch(`${baseUrl}${path}`, { cache: "no-store", ...init, headers });
  } catch (error) {
    throw new ApiError(503, `Cannot reach the API at ${baseUrl}: ${String(error)}`);
  }
  if (!response.ok) {
    throw new ApiError(response.status, await detailOf(response));
  }
  return response;
}

export async function listLinks(filters: Filters): Promise<LinkPage> {
  const response = await apiFetch(`/links?${toApiQuery(filters)}`);
  return (await response.json()) as LinkPage;
}

export async function updateLink(id: string, changes: LinkUpdate): Promise<Link> {
  const response = await apiFetch(`/links/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(changes),
  });
  return (await response.json()) as Link;
}

export async function deleteLink(id: string): Promise<void> {
  await apiFetch(`/links/${encodeURIComponent(id)}`, { method: "DELETE" });
}
