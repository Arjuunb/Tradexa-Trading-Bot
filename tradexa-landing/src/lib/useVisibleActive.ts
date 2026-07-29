import { useEffect, useState, type RefObject } from "react";
import { useInView } from "framer-motion";

/**
 * True only while an element is worth animating: on screen AND in a foreground tab.
 *
 * The landing page runs seven looping demos — a scanner stepping, a terminal
 * typing, a risk gauge sweeping. Five of them ticked forever regardless of
 * where the page was scrolled, and only two stopped when the tab was hidden.
 * The cost is invisible on a desktop with the section in view and obvious
 * everywhere else: loops far below the fold competing with the scroll they are
 * not part of, and a phone warming in a pocket on a backgrounded tab.
 *
 * `requestAnimationFrame` is already throttled in background tabs, but
 * `setInterval` is not — it keeps firing at roughly 1Hz, and each tick still
 * re-renders React. So both signals are needed, not just one.
 *
 * The margin starts loops slightly before they scroll into view, so a demo is
 * already in motion when it arrives rather than visibly kicking off.
 */
export function useVisibleActive(
  ref: RefObject<Element | null>,
  { margin = "200px" }: { margin?: string } = {},
): boolean {
  const inView = useInView(ref, { margin: margin as any });
  const [tabVisible, setTabVisible] = useState(
    () => typeof document === "undefined" || !document.hidden,
  );

  useEffect(() => {
    const onChange = () => setTabVisible(!document.hidden);
    document.addEventListener("visibilitychange", onChange);
    return () => document.removeEventListener("visibilitychange", onChange);
  }, []);

  return inView && tabVisible;
}
