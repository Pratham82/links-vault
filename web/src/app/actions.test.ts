import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { deleteLink, updateLink } from "@/lib/api";
import { SESSION_COOKIE, createSessionToken } from "@/lib/session";

import { removeLink, saveLink, signIn, signOut } from "./actions";

// A tiny in-memory stand-in for Next's request cookies.
const jar = new Map<string, string>();
const cookieStore = {
  get: (name: string) => (jar.has(name) ? { name, value: jar.get(name)! } : undefined),
  set: vi.fn((name: string, value: string) => void jar.set(name, value)),
  delete: vi.fn((name: string) => void jar.delete(name)),
};

vi.mock("next/headers", () => ({
  cookies: async () => cookieStore,
  headers: async () => new Headers(),
}));
vi.mock("next/cache", () => ({ refresh: vi.fn() }));
vi.mock("next/navigation", () => ({
  redirect: vi.fn(() => {
    throw new Error("NEXT_REDIRECT");
  }),
}));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  updateLink: vi.fn(),
  deleteLink: vi.fn(),
}));

const LINK_ID = "0b6c2f7e-9a41-4c1e-8d2f-3a5b6c7d8e9f";

function editForm(): FormData {
  const form = new FormData();
  form.set("note", "hi");
  form.set("tags", "a, b");
  form.set("content_type", "article");
  return form;
}

function passwordForm(password: string): FormData {
  const form = new FormData();
  form.set("password", password);
  return form;
}

beforeEach(() => {
  vi.stubEnv("API_KEY", "api-secret");
  vi.stubEnv("DASHBOARD_PASSWORD", "hunter2");
});

afterEach(() => {
  jar.clear();
  vi.clearAllMocks();
  vi.unstubAllEnvs();
  vi.useRealTimers();
});

describe("editing needs a session", () => {
  it("refuses to save or delete when signed out", async () => {
    expect(await saveLink(LINK_ID, { ok: false }, editForm())).toEqual({
      ok: false,
      error: "Sign in to change links",
    });
    expect((await removeLink(LINK_ID)).ok).toBe(false);
    expect(updateLink).not.toHaveBeenCalled();
    expect(deleteLink).not.toHaveBeenCalled();
  });

  it("refuses a forged cookie", async () => {
    jar.set(SESSION_COOKIE, "9999999999.forged");
    expect((await removeLink(LINK_ID)).ok).toBe(false);
    expect(deleteLink).not.toHaveBeenCalled();
  });

  it("saves and deletes when signed in", async () => {
    jar.set(SESSION_COOKIE, createSessionToken()!);
    expect(await saveLink(LINK_ID, { ok: false }, editForm())).toEqual({ ok: true });
    expect(updateLink).toHaveBeenCalledWith(LINK_ID, {
      note: "hi",
      tags: ["a", "b"],
      content_type: "article",
    });
    expect(await removeLink(LINK_ID)).toEqual({ ok: true });
    expect(deleteLink).toHaveBeenCalledWith(LINK_ID);
  });
});

describe("signIn / signOut", () => {
  it("sets an httpOnly session cookie for the right password", async () => {
    await expect(signIn({ ok: false }, passwordForm("hunter2"))).rejects.toThrow("NEXT_REDIRECT");
    expect(cookieStore.set).toHaveBeenCalledWith(
      SESSION_COOKIE,
      expect.any(String),
      expect.objectContaining({ httpOnly: true, sameSite: "lax", secure: false }),
    );
    // And that cookie now unlocks editing.
    expect(await removeLink(LINK_ID)).toEqual({ ok: true });
  });

  it("rejects a wrong password after a delay", async () => {
    vi.useFakeTimers();
    const pending = signIn({ ok: false }, passwordForm("nope"));
    await vi.advanceTimersByTimeAsync(1000);
    expect(await pending).toEqual({ ok: false, error: "Wrong password" });
    expect(cookieStore.set).not.toHaveBeenCalled();
  });

  it("explains when no password is configured", async () => {
    vi.stubEnv("DASHBOARD_PASSWORD", "");
    const result = await signIn({ ok: false }, passwordForm(""));
    expect(result.error).toMatch(/DASHBOARD_PASSWORD/);
    expect(cookieStore.set).not.toHaveBeenCalled();
  });

  it("signOut clears the cookie", async () => {
    jar.set(SESSION_COOKIE, createSessionToken()!);
    await expect(signOut()).rejects.toThrow("NEXT_REDIRECT");
    expect(jar.has(SESSION_COOKIE)).toBe(false);
  });
});
