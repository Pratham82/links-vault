import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createSessionToken,
  passwordMatches,
  signInConfigured,
  verifySessionToken,
} from "./session";

vi.mock("next/headers", () => ({ cookies: vi.fn(), headers: vi.fn() }));

const NOW = 1_800_000_000;
const THIRTY_DAYS = 30 * 24 * 60 * 60;

beforeEach(() => {
  vi.stubEnv("API_KEY", "api-secret");
  vi.stubEnv("DASHBOARD_PASSWORD", "hunter2");
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("passwordMatches", () => {
  it("accepts only the configured password", () => {
    expect(passwordMatches("hunter2")).toBe(true);
    expect(passwordMatches("hunter3")).toBe(false);
    expect(passwordMatches("")).toBe(false);
  });

  it("rejects everything when no password is set", () => {
    vi.stubEnv("DASHBOARD_PASSWORD", "");
    expect(signInConfigured()).toBe(false);
    expect(passwordMatches("")).toBe(false);
  });
});

describe("session tokens", () => {
  it("round-trips until it expires", () => {
    const token = createSessionToken(NOW)!;
    expect(verifySessionToken(token, NOW)).toBe(true);
    expect(verifySessionToken(token, NOW + THIRTY_DAYS - 1)).toBe(true);
    expect(verifySessionToken(token, NOW + THIRTY_DAYS)).toBe(false);
  });

  it("rejects a token whose expiry was edited", () => {
    const [, signature] = createSessionToken(NOW)!.split(".");
    expect(verifySessionToken(`${NOW + 10 * THIRTY_DAYS}.${signature}`, NOW)).toBe(false);
  });

  it("rejects garbage", () => {
    for (const token of [undefined, "", "abc", "123", "123.", ".sig", "1.2.3", "x.sig"]) {
      expect(verifySessionToken(token, NOW)).toBe(false);
    }
  });

  it("signs everyone out when the password or API key changes", () => {
    const token = createSessionToken(NOW)!;
    vi.stubEnv("DASHBOARD_PASSWORD", "new-password");
    expect(verifySessionToken(token, NOW)).toBe(false);
    vi.stubEnv("DASHBOARD_PASSWORD", "hunter2");
    vi.stubEnv("API_KEY", "rotated");
    expect(verifySessionToken(token, NOW)).toBe(false);
  });

  it("issues and accepts nothing when sign-in isn't configured", () => {
    const token = createSessionToken(NOW)!;
    vi.stubEnv("DASHBOARD_PASSWORD", "");
    expect(createSessionToken(NOW)).toBeNull();
    expect(verifySessionToken(token, NOW)).toBe(false);
  });
});
