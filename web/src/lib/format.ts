import { DISPLAY_TIMEZONE } from "./filters";
import type { ContentType, SourceChannel } from "./types";

export const TYPE_LABELS: Record<ContentType, string> = {
  tweet: "Tweet",
  instagram: "Instagram",
  youtube: "YouTube",
  github_repo: "GitHub repo",
  article: "Article",
  product: "Product",
  docs: "Docs",
  other: "Other",
};

export const SOURCE_LABELS: Record<SourceChannel, string> = {
  telegram: "Telegram",
  desktop: "Desktop",
  whatsapp_import: "WhatsApp import",
  api: "API",
};

const sharedAtFormat = new Intl.DateTimeFormat("en-IN", {
  timeZone: DISPLAY_TIMEZONE,
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

/** "24 Sept 2026, 10:15 pm" in India time, from the API's UTC timestamp. */
export function formatSharedAt(iso: string): string {
  return sharedAtFormat.format(new Date(iso));
}

/** "react, #AI,  tools" → ["react", "ai", "tools"]; the API applies the same rules. */
export function parseTagInput(input: string): string[] {
  const tags: string[] = [];
  for (const raw of input.split(",")) {
    const tag = raw.trim().replace(/^#+/, "").split(/\s+/).join(" ").toLowerCase();
    if (tag && !tags.includes(tag)) tags.push(tag);
  }
  return tags;
}

/** Host without "www.", for links that have no site name yet. */
export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}
