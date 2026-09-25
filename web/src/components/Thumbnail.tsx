"use client";

import { useState } from "react";

interface Props {
  src: string | null;
  // Shown in the placeholder when there's no image or it fails to load.
  label: string;
}

export function Thumbnail({ src, label }: Props) {
  const [failed, setFailed] = useState(false);

  if (!src || failed) {
    return (
      <div className="flex aspect-[1.91/1] w-full items-center justify-center bg-gradient-to-br from-zinc-100 to-zinc-200 text-3xl font-semibold uppercase text-zinc-400 dark:from-zinc-800 dark:to-zinc-900 dark:text-zinc-600">
        {label.slice(0, 1)}
      </div>
    );
  }
  return (
    // A plain <img>, not next/image: previews come from any site's CDN, and next/image
    // would need every one of those hosts allow-listed in next.config.ts.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt=""
      loading="lazy"
      // Some CDNs refuse hotlinked images when they see a foreign Referer.
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
      className="aspect-[1.91/1] w-full bg-zinc-100 object-cover dark:bg-zinc-800"
    />
  );
}
