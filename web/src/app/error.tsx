"use client";

export default function Error({ reset }: { error: Error; reset: () => void }) {
  return (
    <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-6 text-sm text-destructive">
      <p className="font-semibold">Something went wrong</p>
      <button type="button" onClick={reset} className="mt-2 underline">
        Try again
      </button>
    </div>
  );
}
