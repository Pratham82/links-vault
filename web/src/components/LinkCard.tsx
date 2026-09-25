import Link from "next/link";

import { brandLogoFor, siteIconCandidates } from "@/lib/brands";
import { dashboardHref, type Filters } from "@/lib/filters";
import { SOURCE_LABELS, TYPE_LABELS, formatSharedAt, hostOf } from "@/lib/format";
import type { Link as LinkItem, LinkStatus } from "@/lib/types";

import { LinkEditor } from "./LinkEditor";
import { Thumbnail } from "./Thumbnail";

const STATUS_BADGES: Partial<Record<LinkStatus, { label: string; className: string }>> = {
  pending: {
    label: "Fetching preview",
    className: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  },
  failed: {
    label: "No preview",
    className: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400",
  },
  dead: {
    label: "Dead link",
    className: "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300",
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
    <article className="flex w-full flex-col overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
      <a href={link.url} target="_blank" rel="noopener noreferrer" tabIndex={-1}>
        <Thumbnail
          src={link.image_url}
          site={site}
          brand={brandLogoFor(link.normalized_url)}
          iconCandidates={siteIconCandidates(link.normalized_url)}
        />
      </a>

      <div className="flex flex-1 flex-col gap-2 p-4">
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <Link
            href={dashboardHref(filters, { type: link.content_type })}
            className="rounded-full bg-indigo-50 px-2 py-0.5 font-medium text-indigo-700 hover:bg-indigo-100 dark:bg-indigo-950 dark:text-indigo-300"
          >
            {TYPE_LABELS[link.content_type]}
          </Link>
          <span className="truncate text-zinc-500">{site}</span>
          {status && (
            <span className={`rounded-full px-2 py-0.5 font-medium ${status.className}`}>
              {status.label}
            </span>
          )}
        </div>

        <h2 className="line-clamp-2 font-semibold leading-snug">
          <a
            href={link.url}
            target="_blank"
            rel="noopener noreferrer"
            className="break-words hover:underline"
          >
            {link.title ?? link.normalized_url}
          </a>
        </h2>

        {link.description && (
          <p className="line-clamp-3 text-sm text-zinc-600 dark:text-zinc-400">
            {link.description}
          </p>
        )}

        {link.note && (
          <p className="whitespace-pre-line rounded-md bg-zinc-50 px-2.5 py-1.5 text-sm italic text-zinc-700 dark:bg-zinc-900 dark:text-zinc-300">
            {link.note}
          </p>
        )}

        {link.tags.length > 0 && (
          <ul className="flex flex-wrap gap-1.5">
            {link.tags.map((tag) => (
              <li key={tag}>
                <Link
                  href={dashboardHref(filters, { tag })}
                  className="text-xs text-emerald-700 hover:underline dark:text-emerald-400"
                >
                  #{tag}
                </Link>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t border-zinc-100 pt-2 dark:border-zinc-800">
          <p className="text-xs text-zinc-500">
            <time dateTime={link.shared_at}>{formatSharedAt(link.shared_at)}</time>
            {" · "}
            {SOURCE_LABELS[link.source_channel]}
            {link.share_count > 1 && ` · shared ${link.share_count}×`}
          </p>
          <LinkEditor
            linkId={link.id}
            note={link.note}
            tags={link.tags}
            contentType={link.content_type}
          />
        </div>
      </div>
    </article>
  );
}
