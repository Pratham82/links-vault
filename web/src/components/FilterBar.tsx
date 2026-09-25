"use client";

import { AnimatePresence, motion } from "motion/react";
import { Hash, LoaderCircle, Search, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { dashboardHref, hasActiveFilters, type Filters } from "@/lib/filters";
import { SOURCE_LABELS, TYPE_LABELS } from "@/lib/format";
import { CONTENT_TYPES, SOURCE_CHANNELS } from "@/lib/types";

const SEARCH_DELAY_MS = 350;

// Select options, with `null` standing for "no filter". Passing these to <Select items>
// lets the trigger show the label ("YouTube") rather than the raw value ("youtube").
const TYPE_OPTIONS = [
  { value: null, label: "All types" },
  ...CONTENT_TYPES.map((type) => ({ value: type, label: TYPE_LABELS[type] })),
];
const SOURCE_OPTIONS = [
  { value: null, label: "All sources" },
  ...SOURCE_CHANNELS.map((source) => ({ value: source, label: SOURCE_LABELS[source] })),
];

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
      className="flex flex-col gap-3 rounded-xl border bg-card p-3 shadow-xs"
      aria-busy={navigating}
    >
      <div className="relative">
        <Search
          className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <Input
          type="search"
          aria-label="Search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search titles, URLs, descriptions and notes"
          className="h-10 pr-9 pl-9"
        />
        <AnimatePresence>
          {navigating && (
            <motion.span
              key="spinner"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute top-1/2 right-3 -translate-y-1/2 text-muted-foreground"
            >
              <LoaderCircle className="size-4 animate-spin" aria-label="Loading" />
            </motion.span>
          )}
        </AnimatePresence>
      </div>

      <div className="grid grid-cols-2 items-end gap-2 sm:flex sm:flex-wrap">
        <Field label="Type">
          <Select
            items={TYPE_OPTIONS}
            value={filters.type ?? null}
            onValueChange={(type) => apply({ type: type ?? undefined })}
          >
            <SelectTrigger aria-label="Type" className="w-full sm:w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {TYPE_OPTIONS.map((option) => (
                <SelectItem key={option.label} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>

        <Field label="Source">
          <Select
            items={SOURCE_OPTIONS}
            value={filters.source ?? null}
            onValueChange={(source) => apply({ source: source ?? undefined })}
          >
            <SelectTrigger aria-label="Source" className="w-full sm:w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SOURCE_OPTIONS.map((option) => (
                <SelectItem key={option.label} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>

        <Field label="Tag" htmlFor="filter-tag">
          <div className="relative">
            <Hash
              className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <Input
              id="filter-tag"
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
              className="w-full pl-7 sm:w-32"
            />
          </div>
        </Field>

        <Field label="From" htmlFor="filter-from">
          <Input
            id="filter-from"
            type="date"
            value={filters.from ?? ""}
            max={filters.to}
            onChange={(event) => apply({ from: event.target.value || undefined })}
            className="w-full sm:w-auto"
          />
        </Field>

        <Field label="To" htmlFor="filter-to">
          <Input
            id="filter-to"
            type="date"
            value={filters.to ?? ""}
            min={filters.from}
            onChange={(event) => apply({ to: event.target.value || undefined })}
            className="w-full sm:w-auto"
          />
        </Field>

        <AnimatePresence>
          {hasActiveFilters(filters) && (
            <motion.div
              key="clear"
              initial={{ opacity: 0, x: -4 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -4 }}
              transition={{ duration: 0.15 }}
            >
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  setQuery("");
                  startNavigation(() => router.push("/"));
                }}
                className="text-muted-foreground"
              >
                <X data-icon="inline-start" />
                Clear
              </Button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </form>
  );
}

// A caption above each control. Text inputs are tied to theirs with htmlFor; the selects
// are buttons that open a popup, so they get an aria-label instead of a clickable label.
function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor?: string;
  children: ReactNode;
}) {
  const captionClass = "text-xs font-medium text-muted-foreground";
  return (
    <div className="flex flex-col gap-1.5">
      {htmlFor ? (
        <Label htmlFor={htmlFor} className={captionClass}>
          {label}
        </Label>
      ) : (
        <span aria-hidden className={captionClass}>
          {label}
        </span>
      )}
      {children}
    </div>
  );
}
