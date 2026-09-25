import { describe, expect, it } from "vitest";

import { PAGE_SIZE, dashboardHref, hasActiveFilters, parseFilters, toApiQuery } from "./filters";

describe("parseFilters", () => {
  it("reads valid params", () => {
    expect(
      parseFilters({
        type: "tweet",
        source: "whatsapp_import",
        tag: "React",
        q: "  hooks ",
        from: "2026-09-01",
        to: "2026-09-24",
        page: "3",
      }),
    ).toEqual({
      type: "tweet",
      source: "whatsapp_import",
      tag: "react",
      q: "hooks",
      from: "2026-09-01",
      to: "2026-09-24",
      page: 3,
    });
  });

  it("drops invalid values instead of failing", () => {
    expect(
      parseFilters({
        type: "podcast",
        source: "email",
        tag: "  ",
        from: "2026-02-30",
        to: "24/09/2026",
        page: "-2",
      }),
    ).toEqual({ page: 1 });
  });

  it("takes the first of repeated params", () => {
    expect(parseFilters({ type: ["youtube", "tweet"], page: ["2", "5"] })).toMatchObject({
      type: "youtube",
      page: 2,
    });
  });

  it("caps the search length", () => {
    expect(parseFilters({ q: "x".repeat(500) }).q).toHaveLength(200);
  });
});

describe("toApiQuery", () => {
  it("turns calendar days in India into an inclusive range of instants", () => {
    const query = toApiQuery({ from: "2026-09-01", to: "2026-09-30", page: 1 });
    expect(query.get("from")).toBe("2026-09-01T00:00:00+05:30");
    // The API's `to` is exclusive, so the last day ends at the next midnight.
    expect(query.get("to")).toBe("2026-10-01T00:00:00+05:30");
  });

  it("rolls over month and year ends", () => {
    expect(toApiQuery({ to: "2026-12-31", page: 1 }).get("to")).toBe(
      "2027-01-01T00:00:00+05:30",
    );
  });

  it("pages with limit and offset", () => {
    const query = toApiQuery({ page: 3 });
    expect(query.get("limit")).toBe(String(PAGE_SIZE));
    expect(query.get("offset")).toBe(String(2 * PAGE_SIZE));
  });

  it("only sends filters that are set", () => {
    const query = toApiQuery({ type: "docs", tag: "ai", q: "next", page: 1 });
    expect([...query.keys()].sort()).toEqual(["limit", "offset", "q", "tag", "type"]);
  });
});

describe("dashboardHref", () => {
  const filters = { type: "tweet", q: "ai agents", page: 4 } as const;

  it("changing a filter keeps the others and goes back to page 1", () => {
    expect(dashboardHref(filters, { tag: "tools" })).toBe("/?q=ai+agents&type=tweet&tag=tools");
  });

  it("can move between pages", () => {
    expect(dashboardHref(filters, { page: 5 })).toBe("/?q=ai+agents&type=tweet&page=5");
  });

  it("can remove a filter", () => {
    expect(dashboardHref(filters, { type: undefined, q: undefined })).toBe("/");
  });

  it("round-trips through parseFilters", () => {
    const href = dashboardHref({ source: "telegram", from: "2026-09-01", page: 2 }, { page: 2 });
    const params = Object.fromEntries(new URL(href, "http://x").searchParams);
    expect(parseFilters(params)).toEqual({ source: "telegram", from: "2026-09-01", page: 2 });
  });
});

describe("hasActiveFilters", () => {
  it("ignores the page number", () => {
    expect(hasActiveFilters({ page: 3 })).toBe(false);
    expect(hasActiveFilters({ tag: "ai", page: 1 })).toBe(true);
  });
});
