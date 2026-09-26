// The dashboard's sign-in: one password (DASHBOARD_PASSWORD), one signed cookie.
//
// Browsing stays open; editing and deleting need a session. The cookie holds only an expiry
// time and an HMAC signature of it, so the server needs no session table: a cookie is valid
// if the signature matches and the time hasn't passed. The signing key is derived from
// API_KEY (a long random secret the browser never sees) and the password, so changing either
// one signs everybody out.
import "server-only";

import { createHash, createHmac, timingSafeEqual } from "node:crypto";

import { cookies, headers } from "next/headers";

export const SESSION_COOKIE = "lv_session";
const SESSION_SECONDS = 30 * 24 * 60 * 60;

/** The HMAC key for session cookies, or null when sign-in isn't configured. */
function sessionKey(): Buffer | null {
  const password = process.env.DASHBOARD_PASSWORD;
  const apiKey = process.env.API_KEY;
  if (!password || !apiKey) return null;
  return createHmac("sha256", apiKey).update(`dashboard-session\0${password}`).digest();
}

export function signInConfigured(): boolean {
  return sessionKey() !== null;
}

function sign(key: Buffer, payload: string): string {
  return createHmac("sha256", key).update(payload).digest("base64url");
}

/** Compare two strings in constant time, whatever their lengths. */
function safeEqual(a: string, b: string): boolean {
  // Hashing first makes both sides 32 bytes, which timingSafeEqual requires.
  const digest = (value: string) => createHash("sha256").update(value).digest();
  return timingSafeEqual(digest(a), digest(b));
}

export function passwordMatches(input: string): boolean {
  const password = process.env.DASHBOARD_PASSWORD;
  if (!password) return false;
  return safeEqual(input, password);
}

export function createSessionToken(nowSeconds = Math.floor(Date.now() / 1000)): string | null {
  const key = sessionKey();
  if (!key) return null;
  const expires = String(nowSeconds + SESSION_SECONDS);
  return `${expires}.${sign(key, expires)}`;
}

export function verifySessionToken(
  token: string | undefined,
  nowSeconds = Math.floor(Date.now() / 1000),
): boolean {
  const key = sessionKey();
  if (!key || !token) return false;
  const [expires, signature, ...rest] = token.split(".");
  if (rest.length > 0 || !/^\d+$/.test(expires) || !signature) return false;
  return safeEqual(signature, sign(key, expires)) && Number(expires) > nowSeconds;
}

/** True when the current request carries a valid session cookie. */
export async function isSignedIn(): Promise<boolean> {
  const cookieStore = await cookies();
  return verifySessionToken(cookieStore.get(SESSION_COOKIE)?.value);
}

/** Set the session cookie. Only works in a server action or route handler. */
export async function startSession(): Promise<void> {
  const token = createSessionToken();
  if (!token) return;
  // Secure (HTTPS-only) when the dashboard is reached over HTTPS, e.g. behind a TLS proxy.
  // Plain http://localhost:3000 needs a non-secure cookie or Safari drops it.
  const secure = (await headers()).get("x-forwarded-proto") === "https";
  const cookieStore = await cookies();
  cookieStore.set(SESSION_COOKIE, token, {
    httpOnly: true, // page scripts can't read it
    sameSite: "lax", // not sent on cross-site form posts
    secure,
    path: "/",
    maxAge: SESSION_SECONDS,
  });
}

export async function endSession(): Promise<void> {
  const cookieStore = await cookies();
  cookieStore.delete(SESSION_COOKIE);
}
