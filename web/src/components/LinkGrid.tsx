"use client";

import { AnimatePresence, MotionConfig, motion } from "motion/react";
import type { ReactNode } from "react";

// Motion needs client components, but the cards themselves are server components. So the
// page renders <LinkGrid> and <LinkGridItem> (client) and passes each card in as children.

export function LinkGrid({ children }: { children: ReactNode }) {
  return (
    // reducedMotion="user": skip the movement for people who've asked their OS for less.
    <MotionConfig reducedMotion="user">
      <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {/* popLayout: a deleted card leaves the grid at once and the rest slide into place. */}
        <AnimatePresence mode="popLayout">{children}</AnimatePresence>
      </ul>
    </MotionConfig>
  );
}

// Cards fade up one after another on load, capped so a full page doesn't take long.
const STAGGER_S = 0.03;
const MAX_DELAY_S = 0.3;

export function LinkGridItem({ index, children }: { index: number; children: ReactNode }) {
  return (
    <motion.li
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{
        opacity: 1,
        y: 0,
        transition: {
          duration: 0.25,
          ease: "easeOut",
          delay: Math.min(index * STAGGER_S, MAX_DELAY_S),
        },
      }}
      exit={{ opacity: 0, scale: 0.96, transition: { duration: 0.15 } }}
      transition={{ layout: { duration: 0.25, ease: "easeOut" } }}
      className="flex"
    >
      {children}
    </motion.li>
  );
}
