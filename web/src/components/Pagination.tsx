import Link from "next/link";

import { PAGE_SIZE, dashboardHref, type Filters } from "@/lib/filters";

const linkClass =
  "rounded-md border border-zinc-300 px-3 py-1.5 text-sm hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800";

export function Pagination({ filters, total }: { filters: Filters; total: number }) {
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  if (pages === 1) return null;
  const { page } = filters;

  return (
    <nav aria-label="Pages" className="flex items-center justify-center gap-3">
      {page > 1 ? (
        <Link href={dashboardHref(filters, { page: page - 1 })} className={linkClass}>
          ← Newer
        </Link>
      ) : (
        <span className={`${linkClass} pointer-events-none opacity-40`}>← Newer</span>
      )}
      <span className="text-sm text-zinc-500">
        Page {page} of {pages}
      </span>
      {page < pages ? (
        <Link href={dashboardHref(filters, { page: page + 1 })} className={linkClass}>
          Older →
        </Link>
      ) : (
        <span className={`${linkClass} pointer-events-none opacity-40`}>Older →</span>
      )}
    </nav>
  );
}
