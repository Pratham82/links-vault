// Dashboard filters live in the page URL (?type=tweet&q=react&page=2), so every view can be
// bookmarked and the back button works. This module turns that URL into validated filters,
// and filters into the query string the backend's GET /links expects.

import { CONTENT_TYPES, SOURCE_CHANNELS, type ContentType, type SourceChannel } from "./types";

export const PAGE_SIZE = 48;
// Dates in the dashboard are calendar days in India; the API wants exact instants.
export const DISPLAY_TIMEZONE = "Asia/Kolkata";
const DISPLAY_UTC_OFFSET = "+05:30";

export interface Filters {
  type?: ContentType;
  source?: SourceChannel;
  tag?: string;
  q?: string;
  // Calendar days, YYYY-MM-DD, both inclusive.
  from?: string;
  to?: string;
  page: number;
}

export type SearchParams = Record<string, string | string[] | undefined>;

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function first(value: string | string[] | undefined): string | undefined {
  const single = Array.isArray(value) ? value[0] : value;
  const trimmed = single?.trim();
  return trimmed ? trimmed : undefined;
}

function oneOf<T extends string>(allowed: readonly T[], value: string | undefined): T | undefined {
  return allowed.find((option) => option === value);
}

function isRealDate(value: string | undefined): value is string {
  if (!value || !DATE_RE.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  // Rejects 2026-02-30, which Date would otherwise roll over into March.
  return !Number.isNaN(date.getTime()) && date.toISOString().startsWith(value);
}

/** Read filters from the page's search params, dropping anything invalid. */
export function parseFilters(params: SearchParams): Filters {
  const page = Number.parseInt(first(params.page) ?? "1", 10);
  const from = first(params.from);
  const to = first(params.to);
  return {
    type: oneOf(CONTENT_TYPES, first(params.type)),
    source: oneOf(SOURCE_CHANNELS, first(params.source)),
    tag: first(params.tag)?.toLowerCase(),
    q: first(params.q)?.slice(0, 200),
    from: isRealDate(from) ? from : undefined,
    to: isRealDate(to) ? to : undefined,
    page: Number.isFinite(page) && page > 0 ? page : 1,
  };
}

function nextDay(day: string): string {
  const date = new Date(`${day}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().slice(0, 10);
}

/** Query string for GET /links. `to` is exclusive in the API, so it's the day after. */
export function toApiQuery(filters: Filters): URLSearchParams {
  const query = new URLSearchParams();
  if (filters.type) query.set("type", filters.type);
  if (filters.source) query.set("source", filters.source);
  if (filters.tag) query.set("tag", filters.tag);
  if (filters.q) query.set("q", filters.q);
  if (filters.from) query.set("from", `${filters.from}T00:00:00${DISPLAY_UTC_OFFSET}`);
  if (filters.to) query.set("to", `${nextDay(filters.to)}T00:00:00${DISPLAY_UTC_OFFSET}`);
  query.set("limit", String(PAGE_SIZE));
  query.set("offset", String((filters.page - 1) * PAGE_SIZE));
  return query;
}

/** Dashboard URL for `filters` with some fields changed. Changing a filter resets the page. */
export function dashboardHref(filters: Filters, changes: Partial<Filters> = {}): string {
  const next: Filters = { ...filters, page: 1, ...changes };
  const query = new URLSearchParams();
  for (const key of ["q", "type", "source", "tag", "from", "to"] as const) {
    const value = next[key];
    if (value) query.set(key, value);
  }
  if (next.page > 1) query.set("page", String(next.page));
  const search = query.toString();
  return search ? `/?${search}` : "/";
}

export function hasActiveFilters(filters: Filters): boolean {
  return Boolean(
    filters.type || filters.source || filters.tag || filters.q || filters.from || filters.to,
  );
}
