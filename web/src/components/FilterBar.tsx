"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";

import { dashboardHref, hasActiveFilters, type Filters } from "@/lib/filters";
import { SOURCE_LABELS, TYPE_LABELS } from "@/lib/format";
import { CONTENT_TYPES, SOURCE_CHANNELS } from "@/lib/types";

const SEARCH_DELAY_MS = 350;

const fieldClass =
  "rounded-md border border-zinc-300 bg-white px-2.5 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900";

// The page passes the filters from the URL. It remounts this component (via `key`) when
// they change, so the local state below always starts from the current URL.
export function FilterBar({ filters }: { filters: Filters }) {
  const router = useRouter();
  const [navigating, startNavigation] = useTransition();
  const [query, setQuery] = useState(filters.q ?? "");

  function apply(changes: Partial<Filters>) {
    startNavigation(() => router.push(dashboardHref(filters, changes)));
  }

  // Search as you type, once typing pauses.
  useEffect(() => {
    if (query.trim() === (filters.q ?? "")) return;
    const timer = setTimeout(() => {
      startNavigation(() =>
        router.replace(dashboardHref(filters, { q: query.trim() || undefined })),
      );
    }, SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [query, filters, router]);

  return (
    <form
      role="search"
      onSubmit={(event) => {
        event.preventDefault();
        apply({ q: query.trim() || undefined });
      }}
      className="flex flex-wrap items-end gap-2"
      aria-busy={navigating}
    >
      <label className="flex min-w-48 flex-1 flex-col gap-1 text-xs font-medium text-zinc-500">
        Search
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Title, URL, description or note"
          className={fieldClass}
        />
      </label>

      <label className="flex flex-col gap-1 text-xs font-medium text-zinc-500">
        Type
        <select
          value={filters.type ?? ""}
          onChange={(event) =>
            apply({ type: (event.target.value || undefined) as Filters["type"] })
          }
          className={fieldClass}
        >
          <option value="">All types</option>
          {CONTENT_TYPES.map((type) => (
            <option key={type} value={type}>
              {TYPE_LABELS[type]}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1 text-xs font-medium text-zinc-500">
        Source
        <select
          value={filters.source ?? ""}
          onChange={(event) =>
            apply({ source: (event.target.value || undefined) as Filters["source"] })
          }
          className={fieldClass}
        >
          <option value="">All sources</option>
          {SOURCE_CHANNELS.map((source) => (
            <option key={source} value={source}>
              {SOURCE_LABELS[source]}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1 text-xs font-medium text-zinc-500">
        Tag
        <input
          defaultValue={filters.tag ?? ""}
          placeholder="any"
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              apply({ tag: event.currentTarget.value.trim().replace(/^#/, "") || undefined });
            }
          }}
          onBlur={(event) => {
            const tag = event.currentTarget.value.trim().replace(/^#/, "") || undefined;
            if (tag !== filters.tag) apply({ tag });
          }}
          className={`${fieldClass} w-28`}
        />
      </label>

      <label className="flex flex-col gap-1 text-xs font-medium text-zinc-500">
        From
        <input
          type="date"
          value={filters.from ?? ""}
          max={filters.to}
          onChange={(event) => apply({ from: event.target.value || undefined })}
          className={fieldClass}
        />
      </label>

      <label className="flex flex-col gap-1 text-xs font-medium text-zinc-500">
        To
        <input
          type="date"
          value={filters.to ?? ""}
          min={filters.from}
          onChange={(event) => apply({ to: event.target.value || undefined })}
          className={fieldClass}
        />
      </label>

      {hasActiveFilters(filters) && (
        <button
          type="button"
          onClick={() => {
            setQuery("");
            startNavigation(() => router.push("/"));
          }}
          className="rounded-md px-2.5 py-1.5 text-sm text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"
        >
          Clear
        </button>
      )}
    </form>
  );
}
