import { Repeat2 } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { brandLogoFor, siteIconCandidates } from "@/lib/brands";
import { dashboardHref, type Filters } from "@/lib/filters";
import { SOURCE_LABELS, TYPE_LABELS, formatSharedAt, hostOf } from "@/lib/format";
import type { Link as LinkItem, LinkStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

import { LinkEditor } from "./LinkEditor";
import { Thumbnail } from "./Thumbnail";

const STATUS_BADGES: Partial<Record<LinkStatus, { label: string; className: string }>> = {
  pending: {
    label: "Fetching preview",
    className: "bg-amber-500/10 text-amber-700 dark:text-amber-300",
  },
  failed: {
    label: "No preview",
    className: "bg-muted text-muted-foreground",
  },
  dead: {
    label: "Dead link",
    className: "bg-destructive/10 text-destructive",
  },
};

interface Props {
  link: LinkItem;
  filters: Filters;
}

export function LinkCard({ link, filters }: Props) {
  const site = link.site_name ?? hostOf(link.normalized_url);
  const status = STATUS_BADGES[link.status];

  return (
    <Card className="group w-full gap-0 py-0 transition-shadow duration-200 hover:shadow-md hover:ring-foreground/15">
      <a
        href={link.url}
        target="_blank"
        rel="noopener noreferrer"
        tabIndex={-1}
        className="relative block overflow-hidden"
      >
        <Thumbnail
          src={link.image_url}
          site={site}
          brand={brandLogoFor(link.normalized_url)}
          iconCandidates={siteIconCandidates(link.normalized_url)}
        />
        {status && (
          <Badge
            className={cn("absolute top-2.5 left-2.5 shadow-xs backdrop-blur-sm", status.className)}
          >
            {link.status === "pending" && (
              <span className="size-1.5 animate-pulse rounded-full bg-current" aria-hidden />
            )}
            {status.label}
          </Badge>
        )}
      </a>

      <div className="flex flex-1 flex-col gap-2.5 p-4">
        <div className="flex min-w-0 items-center gap-2 text-xs">
          <Badge
            variant="secondary"
            render={<Link href={dashboardHref(filters, { type: link.content_type })} />}
          >
            {TYPE_LABELS[link.content_type]}
          </Badge>
          <span className="truncate text-muted-foreground">{site}</span>
        </div>

        <h2 className="line-clamp-2 font-heading leading-snug font-semibold">
          <a
            href={link.url}
            target="_blank"
            rel="noopener noreferrer"
            className="break-words underline-offset-4 hover:underline"
          >
            {link.title ?? link.normalized_url}
          </a>
        </h2>

        {link.description && (
          <p className="line-clamp-3 text-sm text-muted-foreground">{link.description}</p>
        )}

        {link.note && (
          <p className="border-l-2 border-border pl-3 text-sm whitespace-pre-line text-foreground/80">
            {link.note}
          </p>
        )}

        {link.tags.length > 0 && (
          <ul className="flex flex-wrap gap-1.5">
            {link.tags.map((tag) => (
              <li key={tag}>
                <Badge
                  variant="outline"
                  className="font-normal text-muted-foreground"
                  render={<Link href={dashboardHref(filters, { tag })} />}
                >
                  #{tag}
                </Badge>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t pt-3">
          <p className="flex min-w-0 flex-1 flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
            <time dateTime={link.shared_at}>{formatSharedAt(link.shared_at)}</time>
            <span aria-hidden>·</span>
            {SOURCE_LABELS[link.source_channel]}
            {link.share_count > 1 && (
              <span
                className="flex items-center gap-0.5"
                title={`Shared ${link.share_count} times`}
              >
                <Repeat2 className="size-3.5" aria-hidden />
                <span className="sr-only">shared </span>
                {link.share_count}×
              </span>
            )}
          </p>
          <LinkEditor
            linkId={link.id}
            note={link.note}
            tags={link.tags}
            contentType={link.content_type}
          />
        </div>
      </div>
    </Card>
  );
}
