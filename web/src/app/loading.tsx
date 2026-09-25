import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <div className="flex flex-col gap-6" aria-busy="true" aria-label="Loading links">
      <Skeleton className="h-[7.5rem] rounded-xl" />
      <Skeleton className="h-4 w-32" />
      <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {Array.from({ length: 8 }, (_, i) => (
          <li
            key={i}
            className="flex flex-col overflow-hidden rounded-xl bg-card ring-1 ring-foreground/10"
          >
            <Skeleton className="aspect-[1.91/1] w-full rounded-none" />
            <div className="flex flex-col gap-2.5 p-4">
              <Skeleton className="h-5 w-20 rounded-full" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-2/3" />
              <Skeleton className="mt-2 h-3 w-1/2" />
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
