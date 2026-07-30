import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";

/**
 * A page-owned backdrop.
 *
 * There is no application-wide backdrop any more. Each page paints its own
 * base and its own texture — see `backdrops.tsx`, where they all sit side by
 * side — so a page that forgets one gets the body's flat ink rather than
 * silently inheriting another page's identity.
 *
 * Two things here are load-bearing and neither is obvious.
 *
 * **It portals to the body.** `position: fixed` resolves against the viewport
 * only while no ancestor establishes a containing block, and `transform`,
 * `filter` and `will-change` all do. The page transition animates
 * `filter: blur()` and `y` on the `<main>` these were rendered inside, so the
 * backdrops were being sized to the whole scrolling document instead: measured
 * on /engine, a backdrop that should have been 1280×760 was 1280×3442. Solid
 * fills hid it, but any texture with a scale was stretched four-fold and
 * scrolled with the content. Rendering outside that subtree is the fix; moving
 * the blur out of the transition would only have hidden it until the next
 * transform.
 *
 * **The base gets its own layer, concatenated rather than merged.** `cn()`
 * runs tailwind-merge, which considers `bg-ink` (a colour) and `bg-page-depth`
 * (an image) to be the same `bg` utility and silently drops the first.
 * Backdrops declaring both rendered with a transparent base and leaned on the
 * body colour behind them — which happened to look right, and would have
 * stopped the moment a page wanted a base the body does not have.
 */
export function Ambient({
  base,
  children,
  className,
}: {
  /** Background utilities for this page's base layer, e.g. "bg-navy". */
  base: string;
  children?: ReactNode;
  className?: string;
}) {
  // document.body is not available until after mount in the general case, and
  // reading it during render would make this component unsafe to server-render
  // later. One state flip costs nothing on a layer nobody interacts with.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted) return null;

  return createPortal(
    <div
      aria-hidden
      className={cn("pointer-events-none fixed inset-0 -z-10 overflow-hidden", className)}
    >
      <div className={`absolute inset-0 ${base}`} />
      {children}
    </div>,
    document.body,
  );
}
