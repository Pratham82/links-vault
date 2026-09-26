// Proxy (called middleware before Next.js 16) runs before any page renders. It sends
// signed-out browsers to /login with a plain 307, so they never see a half-streamed page.
//
// It's a shortcut, not the lock: the page, the thumbnail route and the server actions each
// check the session themselves, so nothing leaks even if a request skips this file.
import { NextResponse, type NextRequest } from "next/server";

import { SESSION_COOKIE, verifySessionToken } from "@/lib/session";

export default function proxy(request: NextRequest) {
  // Only page loads. Server actions (POST) answer with their own "sign in" error instead.
  if (request.method !== "GET") return NextResponse.next();
  if (verifySessionToken(request.cookies.get(SESSION_COOKIE)?.value)) return NextResponse.next();
  return NextResponse.redirect(new URL("/login", request.url));
}

export const config = {
  // Everything except the sign-in page, thumbnails (they answer 401 themselves) and
  // Next.js's own static files.
  matcher: ["/((?!login|thumbnails|_next/|favicon\\.ico).*)"],
};
