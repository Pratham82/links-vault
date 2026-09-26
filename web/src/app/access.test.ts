// Everything that shows data needs a session: the page redirects to /login, and the
// thumbnail proxy refuses to fetch.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch, listLinks } from "@/lib/api";
import { SESSION_COOKIE, createSessionToken } from "@/lib/session";

import Home from "./page";
import { GET as getThumbnail } from "./thumbnails/[file]/route";

const jar = new Map<string, string>();

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => (jar.has(name) ? { name, value: jar.get(name)! } : undefined),
  }),
  headers: async () => new Headers(),
}));
vi.mock("next/navigation", () => ({
  redirect: vi.fn((to: string) => {
    throw new Error(`NEXT_REDIRECT ${to}`);
  }),
}));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  apiFetch: vi.fn(),
  listLinks: vi.fn(),
}));

const THUMB = "0b6c2f7e-9a41-4c1e-8d2f-3a5b6c7d8e9f.jpg";

function thumbnail(file = THUMB): Promise<Response> {
  return getThumbnail(new Request(`http://dash.test/thumbnails/${file}`), {
    params: Promise.resolve({ file }),
  });
}

beforeEach(() => {
  vi.stubEnv("API_KEY", "api-secret");
  vi.stubEnv("DASHBOARD_PASSWORD", "hunter2");
});

afterEach(() => {
  jar.clear();
  vi.clearAllMocks();
  vi.unstubAllEnvs();
});

describe("dashboard page", () => {
  it("sends signed-out visitors to /login without loading links", async () => {
    await expect(Home({ searchParams: Promise.resolve({}) } as PageProps<"/">)).rejects.toThrow(
      "NEXT_REDIRECT /login",
    );
    expect(listLinks).not.toHaveBeenCalled();
  });

  it("redirects when sign-in isn't configured, even with an old cookie", async () => {
    jar.set(SESSION_COOKIE, createSessionToken()!);
    vi.stubEnv("DASHBOARD_PASSWORD", "");
    await expect(Home({ searchParams: Promise.resolve({}) } as PageProps<"/">)).rejects.toThrow(
      "NEXT_REDIRECT /login",
    );
  });

  it("loads links for a signed-in visitor", async () => {
    jar.set(SESSION_COOKIE, createSessionToken()!);
    vi.mocked(listLinks).mockResolvedValue({ items: [], total: 0, limit: 48, offset: 0 });
    await Home({ searchParams: Promise.resolve({}) } as PageProps<"/">);
    expect(listLinks).toHaveBeenCalledOnce();
  });
});

describe("thumbnail proxy", () => {
  it("refuses signed-out browsers", async () => {
    const response = await thumbnail();
    expect(response.status).toBe(401);
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("serves the API's image to signed-in browsers", async () => {
    jar.set(SESSION_COOKIE, createSessionToken()!);
    vi.mocked(apiFetch).mockResolvedValue(
      new Response("img", { headers: { "Content-Type": "image/jpeg" } }),
    );
    const response = await thumbnail();
    expect(response.status).toBe(200);
    expect(response.headers.get("Content-Type")).toBe("image/jpeg");
    expect(apiFetch).toHaveBeenCalledWith(`/thumbnails/${THUMB}`);
  });
});
