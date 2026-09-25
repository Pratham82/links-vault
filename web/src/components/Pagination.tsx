import { ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import { PAGE_SIZE, dashboardHref, type Filters } from "@/lib/filters";
import { cn } from "@/lib/utils";

const linkClass = buttonVariants({ variant: "outline" });

export function Pagination({ filters, total }: { filters: Filters; total: number }) {
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  if (pages === 1) return null;
  const { page } = filters;

  return (
    <nav aria-label="Pages" className="flex items-center justify-center gap-3">
      {page > 1 ? (
        <Link href={dashboardHref(filters, { page: page - 1 })} className={linkClass}>
          <ChevronLeft data-icon="inline-start" aria-hidden />
          Newer
        </Link>
      ) : (
        <span className={cn(linkClass, "pointer-events-none opacity-40")}>
          <ChevronLeft data-icon="inline-start" aria-hidden />
          Newer
        </span>
      )}
      <span className="text-sm text-muted-foreground tabular-nums">
        Page {page} of {pages}
      </span>
      {page < pages ? (
        <Link href={dashboardHref(filters, { page: page + 1 })} className={linkClass}>
          Older
          <ChevronRight data-icon="inline-end" aria-hidden />
        </Link>
      ) : (
        <span className={cn(linkClass, "pointer-events-none opacity-40")}>
          Older
          <ChevronRight data-icon="inline-end" aria-hidden />
        </span>
      )}
    </nav>
  );
}
