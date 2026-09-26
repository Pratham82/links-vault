import type { Metadata } from "next";
import { Geist } from "next/font/google";
import Link from "next/link";
import { LibraryBig, LogOut } from "lucide-react";

import { signOut } from "@/app/actions";
import { Button } from "@/components/ui/button";
import { isSignedIn } from "@/lib/session";
import { cn } from "@/lib/utils";

import "./globals.css";

// Self-hosted by Next.js at build time; no request to Google from the browser.
const geist = Geist({ subsets: ["latin"], variable: "--font-geist-sans" });

export const metadata: Metadata = {
  title: "Link Vault",
  description: "Every link I've shared, in one place.",
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  const signedIn = await isSignedIn();

  return (
    <html lang="en" className={cn("h-full bg-background antialiased", geist.variable)}>
      <body className="min-h-full bg-muted/40">
        <header className="sticky top-0 z-40 border-b bg-background/80 backdrop-blur-md">
          <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">
            <Link
              href="/"
              className="flex items-center gap-2 font-heading text-base font-semibold tracking-tight"
            >
              <span className="flex size-7 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                <LibraryBig className="size-4" aria-hidden />
              </span>
              Link Vault
            </Link>
            {signedIn && (
              <form action={signOut}>
                <Button type="submit" variant="ghost" size="sm" className="text-muted-foreground">
                  <LogOut data-icon="inline-start" aria-hidden />
                  Sign out
                </Button>
              </form>
            )}
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
