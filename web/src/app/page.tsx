import { Inbox, SearchX } from "lucide-react";
import Link from "next/link";

import { FilterBar } from "@/components/FilterBar";
import { LinkCard } from "@/components/LinkCard";
import { LinkGrid, LinkGridItem } from "@/components/LinkGrid";
import { Pagination } from "@/components/Pagination";
import { ApiError, listLinks } from "@/lib/api";
import { requireSession } from "@/lib/session";
import { PAGE_SIZE, dashboardHref, hasActiveFilters, parseFilters } from "@/lib/filters";
import type { LinkPage } from "@/lib/types";

export default async function Home(props: PageProps<"/">) {
  await requireSession();
  const filters = parseFilters(await props.searchParams);

  let page: LinkPage;
  try {
    page = await listLinks(filters);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    return (
      <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-6 text-sm text-destructive">
        <p className="font-semibold">Couldn&apos;t load links</p>
        <p className="mt-1">{error.message}</p>
      </div>
    );
  }

  const firstShown = page.total === 0 ? 0 : page.offset + 1;
  const lastShown = Math.min(page.offset + PAGE_SIZE, page.total);

  return (
    <div className="flex flex-col gap-6">
      <FilterBar key={dashboardHref(filters)} filters={filters} />

      <p className="text-sm text-muted-foreground tabular-nums">
        {page.total === 0
          ? "No links"
          : `${firstShown}–${lastShown} of ${page.total} link${page.total === 1 ? "" : "s"}`}
      </p>

      {page.items.length > 0 ? (
        <LinkGrid>
          {page.items.map((link, index) => (
            <LinkGridItem key={link.id} index={index}>
              <LinkCard link={link} filters={filters} />
            </LinkGridItem>
          ))}
        </LinkGrid>
      ) : (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed bg-card/50 p-12 text-center text-sm text-muted-foreground">
          {hasActiveFilters(filters) ? (
            <>
              <SearchX className="size-8 text-muted-foreground/60" aria-hidden />
              <p>
                Nothing matches these filters.{" "}
                <Link href="/" className="font-medium text-foreground underline underline-offset-4">
                  Clear them
                </Link>
              </p>
            </>
          ) : (
            <>
              <Inbox className="size-8 text-muted-foreground/60" aria-hidden />
              <p>No links yet. Share one to the Telegram bot, or import your WhatsApp history.</p>
            </>
          )}
        </div>
      )}

      <Pagination filters={filters} total={page.total} />
    </div>
  );
}
