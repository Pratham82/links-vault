// Mirrors the backend's Pydantic schemas (backend/app/schemas.py).

export const CONTENT_TYPES = [
  "tweet",
  "instagram",
  "youtube",
  "github_repo",
  "article",
  "product",
  "docs",
  "other",
] as const;
export type ContentType = (typeof CONTENT_TYPES)[number];

export const SOURCE_CHANNELS = ["telegram", "desktop", "whatsapp_import", "api"] as const;
export type SourceChannel = (typeof SOURCE_CHANNELS)[number];

export type LinkStatus = "pending" | "enriched" | "failed" | "dead";

export interface Link {
  id: string;
  url: string;
  normalized_url: string;
  source_channel: SourceChannel;
  sender: string;
  note: string | null;
  title: string | null;
  description: string | null;
  image_url: string | null;
  site_name: string | null;
  content_type: ContentType;
  tags: string[];
  status: LinkStatus;
  share_count: number;
  shared_at: string;
  created_at: string;
  updated_at: string;
}

export interface LinkPage {
  items: Link[];
  total: number;
  limit: number;
  offset: number;
}

export interface LinkUpdate {
  note?: string | null;
  tags?: string[];
  content_type?: ContentType;
}
