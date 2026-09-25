"use client";

import { useState } from "react";

import type { BrandLogo } from "@/lib/brands";

interface Props {
  src: string | null;
  // Shown under the logo when there's no preview image, or it fails to load.
  site: string;
  // The site's official logo, when we have one (see lib/brands.ts).
  brand?: BrandLogo;
  // Otherwise, icons the site serves itself, tried in order.
  iconCandidates: string[];
}

const frameClass = "aspect-[1.91/1] w-full";

export function Thumbnail({ src, site, brand, iconCandidates }: Props) {
  const [imageFailed, setImageFailed] = useState(false);

  if (src && !imageFailed) {
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
        onError={() => setImageFailed(true)}
        className={`${frameClass} bg-zinc-100 object-cover dark:bg-zinc-800`}
      />
    );
  }
  return <SiteMark site={site} brand={brand} iconCandidates={iconCandidates} />;
}

// The fallback, styled like a tinted iOS home-screen icon: the site's logo in greyscale on a
// rounded tile, with the site's name underneath.
function SiteMark({ site, brand, iconCandidates }: Omit<Props, "src">) {
  const [iconIndex, setIconIndex] = useState(0);
  const icon = brand ? undefined : iconCandidates[iconIndex];

  return (
    <div
      className={`${frameClass} flex flex-col items-center justify-center gap-2.5 bg-gradient-to-br from-zinc-100 to-zinc-200 dark:from-zinc-900 dark:to-zinc-800`}
    >
      <div className="flex size-14 items-center justify-center overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-zinc-900/5 dark:bg-zinc-950 dark:ring-white/10">
        {brand ? (
          <svg
            role="img"
            aria-label={brand.title}
            viewBox="0 0 24 24"
            className="size-7 fill-zinc-600 dark:fill-zinc-300"
          >
            <path d={brand.path} />
          </svg>
        ) : icon ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            key={icon}
            src={icon}
            alt=""
            loading="lazy"
            referrerPolicy="no-referrer"
            onError={() => setIconIndex((index) => index + 1)}
            // The apple-touch-icon fills the tile like an app icon; a favicon is small, so
            // it sits in the middle. Greyscale either way, to match the brand logos.
            className={`grayscale opacity-80 dark:opacity-70 ${
              iconIndex === 0 ? "size-full object-cover" : "size-7 object-contain"
            }`}
          />
        ) : (
          <GlobeIcon />
        )}
      </div>
      <span className="max-w-[80%] truncate text-xs font-medium tracking-wide text-zinc-500 dark:text-zinc-400">
        {site}
      </span>
    </div>
  );
}

function GlobeIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      fill="none"
      strokeWidth={1.5}
      className="size-7 stroke-zinc-500 dark:stroke-zinc-400"
    >
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3c2.5 2.7 3.75 5.7 3.75 9S14.5 18.3 12 21c-2.5-2.7-3.75-5.7-3.75-9S9.5 5.7 12 3Z" />
    </svg>
  );
}
