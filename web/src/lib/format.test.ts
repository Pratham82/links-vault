import { describe, expect, it } from "vitest";

import { formatSharedAt, hostOf, parseTagInput } from "./format";

describe("formatSharedAt", () => {
  it("shows the time in India", () => {
    // 16:45 UTC is 10:15 pm in Kolkata.
    const text = formatSharedAt("2026-09-24T16:45:00Z");
    expect(text).toContain("24");
    expect(text).toContain("2026");
    expect(text).toMatch(/10:15\s?pm/i);
  });

  it("moves late-evening UTC times to the next day", () => {
    expect(formatSharedAt("2026-09-24T20:00:00Z")).toContain("25");
  });
});

describe("parseTagInput", () => {
  it("splits, trims, lowercases and dedupes", () => {
    expect(parseTagInput(" React, #AI,  tools ,react,, machine   learning")).toEqual([
      "react",
      "ai",
      "tools",
      "machine learning",
    ]);
  });

  it("returns no tags for empty input", () => {
    expect(parseTagInput("  ,  ")).toEqual([]);
  });
});

describe("hostOf", () => {
  it("drops www", () => {
    expect(hostOf("https://www.example.com/a")).toBe("example.com");
  });

  it("falls back to the input for non-URLs", () => {
    expect(hostOf("not a url")).toBe("not a url");
  });
});
