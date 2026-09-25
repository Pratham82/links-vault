// Official logos for the sites links usually come from, shown when a link has no preview
// image. They come from simple-icons (CC0), one SVG path per brand. Some brands (LinkedIn,
// Amazon, Flipkart…) had their logos removed from simple-icons at their own request; those
// fall back to the site's own icon in the Thumbnail component.
//
// Only imported by server components: the card passes the chosen path down as a prop, so
// the browser never downloads the logo collection.

import {
  siApple,
  siArxiv,
  siBehance,
  siBluesky,
  siChessdotcom,
  siDevdotto,
  siDiscord,
  siDribbble,
  siDropbox,
  siFacebook,
  siFigma,
  siFreepik,
  siGithub,
  siGitlab,
  siGoodreads,
  siGoogle,
  siGoogledocs,
  siGoogledrive,
  siGooglemaps,
  siGoogleplay,
  siHashnode,
  siHuggingface,
  siImdb,
  siInstagram,
  siLetterboxd,
  siLichess,
  siMastodon,
  siMdnwebdocs,
  siMedium,
  siNetflix,
  siNotion,
  siNpm,
  siPaytm,
  siPinterest,
  siProducthunt,
  siPython,
  siQuora,
  siReadthedocs,
  siReddit,
  siSnapchat,
  siSoundcloud,
  siSpotify,
  siStackoverflow,
  siSubstack,
  siSwiggy,
  siTelegram,
  siThreads,
  siTiktok,
  siTwitch,
  siUdemy,
  siVercel,
  siVimeo,
  siWhatsapp,
  siWikipedia,
  siX,
  siYcombinator,
  siYoutube,
  siZomato,
  siZoom,
  type SimpleIcon,
} from "simple-icons";

export interface BrandLogo {
  title: string;
  // SVG path data on a 24×24 viewBox.
  path: string;
}

// Keyed by host without "www."; subdomains match too (blog.medium.com → medium.com).
const BRANDS: Record<string, SimpleIcon> = {
  "x.com": siX,
  "twitter.com": siX,
  "instagram.com": siInstagram,
  "youtube.com": siYoutube,
  "youtu.be": siYoutube,
  "github.com": siGithub,
  "gist.github.com": siGithub,
  "gitlab.com": siGitlab,
  "medium.com": siMedium,
  "facebook.com": siFacebook,
  "fb.watch": siFacebook,
  "reddit.com": siReddit,
  "redd.it": siReddit,
  "google.com": siGoogle,
  "drive.google.com": siGoogledrive,
  "docs.google.com": siGoogledocs,
  "maps.google.com": siGooglemaps,
  "maps.app.goo.gl": siGooglemaps,
  "play.google.com": siGoogleplay,
  "udemy.com": siUdemy,
  "t.me": siTelegram,
  "telegram.org": siTelegram,
  "whatsapp.com": siWhatsapp,
  "wa.me": siWhatsapp,
  "spotify.com": siSpotify,
  "netflix.com": siNetflix,
  "stackoverflow.com": siStackoverflow,
  "npmjs.com": siNpm,
  "vercel.com": siVercel,
  "notion.so": siNotion,
  "notion.site": siNotion,
  "figma.com": siFigma,
  "dribbble.com": siDribbble,
  "behance.net": siBehance,
  "pinterest.com": siPinterest,
  "pin.it": siPinterest,
  "threads.net": siThreads,
  "threads.com": siThreads,
  "substack.com": siSubstack,
  "news.ycombinator.com": siYcombinator,
  "dev.to": siDevdotto,
  "hashnode.com": siHashnode,
  "hashnode.dev": siHashnode,
  "producthunt.com": siProducthunt,
  "apple.com": siApple,
  "wikipedia.org": siWikipedia,
  "freepik.com": siFreepik,
  "tiktok.com": siTiktok,
  "discord.com": siDiscord,
  "discord.gg": siDiscord,
  "python.org": siPython,
  "developer.mozilla.org": siMdnwebdocs,
  "readthedocs.io": siReadthedocs,
  "huggingface.co": siHuggingface,
  "arxiv.org": siArxiv,
  "imdb.com": siImdb,
  "quora.com": siQuora,
  "snapchat.com": siSnapchat,
  "bsky.app": siBluesky,
  "mastodon.social": siMastodon,
  "twitch.tv": siTwitch,
  "vimeo.com": siVimeo,
  "soundcloud.com": siSoundcloud,
  "swiggy.com": siSwiggy,
  "zomato.com": siZomato,
  "paytm.com": siPaytm,
  "dropbox.com": siDropbox,
  "zoom.us": siZoom,
  "letterboxd.com": siLetterboxd,
  "goodreads.com": siGoodreads,
  "chess.com": siChessdotcom,
  "lichess.org": siLichess,
};

/** The host of `url` without "www.", or undefined if it isn't a URL. */
export function hostnameOf(url: string): string | undefined {
  try {
    return new URL(url).hostname.toLowerCase().replace(/^www\./, "") || undefined;
  } catch {
    return undefined;
  }
}

/** The official logo for the site `url` is on, most specific host first. */
export function brandLogoFor(url: string): BrandLogo | undefined {
  const host = hostnameOf(url);
  if (!host) return undefined;
  const labels = host.split(".");
  // docs.google.com → docs.google.com, then google.com; never the bare TLD.
  for (let i = 0; i < labels.length - 1; i++) {
    const icon = BRANDS[labels.slice(i).join(".")];
    if (icon) return { title: icon.title, path: icon.path };
  }
  return undefined;
}

/** Icons a site usually serves itself, best first: the 180px apple-touch-icon, then favicon. */
export function siteIconCandidates(url: string): string[] {
  const host = hostnameOf(url);
  if (!host) return [];
  const origin = new URL(url).origin;
  return [`${origin}/apple-touch-icon.png`, `${origin}/favicon.ico`];
}
