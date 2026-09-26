import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SESSION_COOKIE, createSessionToken } from "@/lib/session";

import proxy from "./proxy";

vi.mock("next/headers", () => ({ cookies: vi.fn(), headers: vi.fn() }));

function request(method = "GET", cookie?: string): NextRequest {
  const headers = new Headers(cookie ? { cookie: `${SESSION_COOKIE}=${cookie}` } : {});
  return new NextRequest("http://dash.test/?tag=react", { method, headers });
}

beforeEach(() => {
  vi.stubEnv("API_KEY", "api-secret");
  vi.stubEnv("DASHBOARD_PASSWORD", "hunter2");
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("proxy", () => {
  it("redirects a signed-out page load to /login", () => {
    const response = proxy(request());
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://dash.test/login");
  });

  it("redirects a forged cookie", () => {
    expect(proxy(request("GET", "9999999999.forged")).status).toBe(307);
  });

  it("lets a signed-in page load through", () => {
    const response = proxy(request("GET", createSessionToken()!));
    expect(response.headers.get("location")).toBeNull();
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("leaves server action POSTs to the action's own check", () => {
    expect(proxy(request("POST")).headers.get("location")).toBeNull();
  });
});
