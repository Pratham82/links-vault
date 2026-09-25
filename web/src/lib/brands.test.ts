import { describe, expect, it } from "vitest";

import { brandLogoFor, hostnameOf, siteIconCandidates } from "./brands";

describe("brandLogoFor", () => {
  it.each([
    ["https://x.com/someone/status/1", "X"],
    ["https://www.instagram.com/reel/abc/", "Instagram"],
    ["https://www.youtube.com/watch?v=1", "YouTube"],
    ["https://github.com/astral-sh/uv", "GitHub"],
    ["https://drive.google.com/drive/folders/1", "Google Drive"],
    ["https://www.google.com/search?q=x", "Google"],
    // Subdomains fall back to the site they belong to.
    ["https://blog.medium.com/post", "Medium"],
    ["https://someone.substack.com/p/post", "Substack"],
    ["https://m.facebook.com/story", "Facebook"],
  ])("%s → %s", (url, title) => {
    const logo = brandLogoFor(url);
    expect(logo?.title).toBe(title);
    expect(logo?.path).toMatch(/^M/);
  });

  it.each([
    "https://www.linkedin.com/posts/x",
    "https://www.amazon.in/dp/B0",
    "https://example.com/post",
    "not a url",
  ])("has no logo for %s", (url) => {
    expect(brandLogoFor(url)).toBeUndefined();
  });

  it("never matches on the bare top-level domain", () => {
    expect(brandLogoFor("https://something.com")).toBeUndefined();
  });
});

describe("siteIconCandidates", () => {
  it("tries the high-resolution icon first, then the favicon", () => {
    expect(siteIconCandidates("https://www.linkedin.com/posts/x?y=1")).toEqual([
      "https://www.linkedin.com/apple-touch-icon.png",
      "https://www.linkedin.com/favicon.ico",
    ]);
  });

  it("returns nothing for a non-URL", () => {
    expect(siteIconCandidates("nope")).toEqual([]);
  });
});

describe("hostnameOf", () => {
  it("drops www and lowercases", () => {
    expect(hostnameOf("https://WWW.Example.COM/a")).toBe("example.com");
  });
});
