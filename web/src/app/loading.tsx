export default function Loading() {
  return (
    <div className="flex flex-col gap-6" aria-busy="true" aria-label="Loading links">
      <div className="h-14 animate-pulse rounded-lg bg-zinc-200 dark:bg-zinc-800" />
      <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {Array.from({ length: 8 }, (_, i) => (
          <li key={i} className="h-72 animate-pulse rounded-xl bg-zinc-200 dark:bg-zinc-800" />
        ))}
      </ul>
    </div>
  );
}
