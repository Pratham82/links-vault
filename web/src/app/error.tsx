"use client";

export default function Error({ reset }: { error: Error; reset: () => void }) {
  return (
    <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
      <p className="font-semibold">Something went wrong</p>
      <button type="button" onClick={reset} className="mt-2 underline">
        Try again
      </button>
    </div>
  );
}
