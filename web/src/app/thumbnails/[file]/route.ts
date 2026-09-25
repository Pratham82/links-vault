// Serves the worker's cached thumbnails to the browser.
//
// The API's /thumbnails/{file} needs the X-API-Key header, which a browser <img> can't
// send (and must never know). This handler lives at the same path on the dashboard, so a
// link's image_url ("/thumbnails/<id>.jpg") works as an <img src> unchanged.

import { ApiError, apiFetch } from "@/lib/api";

// Only the names the worker generates: "<uuid>.<ext>". Same rule as the API.
const FILENAME_RE = /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}\.(jpg|png|webp|gif)$/;

export async function GET(_request: Request, ctx: RouteContext<"/thumbnails/[file]">) {
  const { file } = await ctx.params;
  if (!FILENAME_RE.test(file)) {
    return new Response("Not found", { status: 404 });
  }
  try {
    const upstream = await apiFetch(`/thumbnails/${file}`);
    return new Response(upstream.body, {
      headers: {
        "Content-Type": upstream.headers.get("Content-Type") ?? "application/octet-stream",
        // A thumbnail never changes for a given name.
        "Cache-Control": "private, max-age=31536000, immutable",
      },
    });
  } catch (error) {
    const status = error instanceof ApiError && error.status === 404 ? 404 : 502;
    return new Response(status === 404 ? "Not found" : "Thumbnail unavailable", { status });
  }
}
