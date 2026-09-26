import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, deleteLink, listLinks, updateLink } from "./api";

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  vi.stubEnv("API_BASE_URL", "http://api.test:8000/");
  vi.stubEnv("API_KEY", "secret");
});

afterEach(() => {
  fetchMock.mockReset();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("listLinks", () => {
  it("sends the API key and the filters", async () => {
    fetchMock.mockResolvedValue(json({ items: [], total: 0, limit: 48, offset: 0 }));

    const page = await listLinks({ type: "tweet", page: 2 });

    expect(page.total).toBe(0);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://api.test:8000/links?type=tweet&limit=48&offset=48");
    expect(new Headers(init?.headers).get("X-API-Key")).toBe("secret");
    expect(init?.cache).toBe("no-store");
  });

  it("turns error responses into ApiError with the API's detail", async () => {
    fetchMock.mockResolvedValue(json({ detail: "Missing or invalid X-API-Key header" }, 401));

    await expect(listLinks({ page: 1 })).rejects.toMatchObject({
      name: "ApiError",
      status: 401,
      message: "Missing or invalid X-API-Key header",
    });
  });

  it("joins FastAPI validation errors", async () => {
    fetchMock.mockResolvedValue(json({ detail: [{ msg: "bad a" }, { msg: "bad b" }] }, 422));
    await expect(listLinks({ page: 1 })).rejects.toThrow("bad a; bad b");
  });

  it("reports an unreachable API as 503", async () => {
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));
    const error = await listLinks({ page: 1 }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(503);
    expect((error as ApiError).message).toContain("http://api.test:8000");
  });

  it("refuses to run without an API key", async () => {
    vi.stubEnv("API_KEY", "");
    await expect(listLinks({ page: 1 })).rejects.toThrow("API_KEY is not set");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each(["", "   ", "/", "links-api.example.com"])(
    "explains a blank or partial API_BASE_URL (%j)",
    async (value) => {
      vi.stubEnv("API_BASE_URL", value);
      await expect(listLinks({ page: 1 })).rejects.toThrow(
        "API_BASE_URL must be the API's full URL",
      );
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

  it("tolerates stray whitespace around API_BASE_URL", async () => {
    vi.stubEnv("API_BASE_URL", " https://api.test/ ");
    fetchMock.mockResolvedValue(json({ items: [], total: 0, limit: 48, offset: 0 }));
    await listLinks({ page: 1 });
    expect(fetchMock.mock.calls[0][0]).toBe("https://api.test/links?limit=48&offset=0");
  });
});

describe("updateLink and deleteLink", () => {
  it("PATCHes the changes as JSON", async () => {
    fetchMock.mockResolvedValue(json({ id: "abc", tags: ["ai"] }));

    await updateLink("abc", { tags: ["ai"], note: null });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://api.test:8000/links/abc");
    expect(init?.method).toBe("PATCH");
    expect(JSON.parse(String(init?.body))).toEqual({ tags: ["ai"], note: null });
    expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
  });

  it("DELETEs the link", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await deleteLink("abc");
    expect(fetchMock.mock.calls[0][1]?.method).toBe("DELETE");
  });
});
