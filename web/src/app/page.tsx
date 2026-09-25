import Link from "next/link";

import { FilterBar } from "@/components/FilterBar";
import { LinkCard } from "@/components/LinkCard";
import { Pagination } from "@/components/Pagination";
import { ApiError, listLinks } from "@/lib/api";
import { PAGE_SIZE, dashboardHref, hasActiveFilters, parseFilters } from "@/lib/filters";
import type { LinkPage } from "@/lib/types";

export default async function Home(props: PageProps<"/">) {
  const filters = parseFilters(await props.searchParams);

  let page: LinkPage;
  try {
    page = await listLinks(filters);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
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

      <p className="text-sm text-zinc-500">
        {page.total === 0
          ? "No links"
          : `${firstShown}–${lastShown} of ${page.total} link${page.total === 1 ? "" : "s"}`}
      </p>

      {page.items.length > 0 ? (
        <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {page.items.map((link) => (
            <li key={link.id} className="flex">
              <LinkCard link={link} filters={filters} />
            </li>
          ))}
        </ul>
      ) : (
        <div className="rounded-xl border border-dashed border-zinc-300 p-10 text-center text-sm text-zinc-500 dark:border-zinc-700">
          {hasActiveFilters(filters) ? (
            <>
              Nothing matches these filters.{" "}
              <Link href="/" className="underline">
                Clear them
              </Link>
            </>
          ) : (
            "No links yet. Share one to the Telegram bot, or import your WhatsApp history."
          )}
        </div>
      )}

      <Pagination filters={filters} total={page.total} />
    </div>
  );
}
