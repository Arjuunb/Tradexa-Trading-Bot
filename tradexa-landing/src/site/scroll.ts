/**
 * Scroll position across navigations.
 *
 * Three things were fighting over where a page starts, and the reader lost:
 *
 *  1. The browser. `history.scrollRestoration` defaults to "auto", so on Back
 *     Chrome restores its own recorded offset — progressively, as the document
 *     grows, over several hundred milliseconds. Any position we set is then
 *     dragged somewhere else a frame later. It has to be turned off before we
 *     can be the ones deciding.
 *  2. The stylesheet. `html { scroll-behavior: smooth }` exists so anchor links
 *     glide, and it applies to programmatic scrolls too — so a restore
 *     *animated* a thousand pixels instead of simply being there.
 *  3. Us. Restoring on the frame the route changes is too early: the document
 *     is still the height of the chrome, the offset clamps short, and the
 *     clamped value overwrites the one we were about to restore.
 *
 * Turning off (1) means reloads no longer restore either, so positions are
 * mirrored into sessionStorage — keyed by the router's history key, which is
 * stored in history.state and therefore survives a reload just as the entry
 * does.
 */

const KEY = "nx:scroll";

function load(): Map<string, number> {
  try {
    const raw = sessionStorage.getItem(KEY);
    return raw ? new Map(JSON.parse(raw) as [string, number][]) : new Map();
  } catch {
    // Private mode, storage disabled, or corrupt JSON. In-memory only is a
    // perfectly good degradation — Back still works within the session.
    return new Map();
  }
}

const positions: Map<string, number> = typeof sessionStorage === "undefined" ? new Map() : load();

let flushHandle = 0;
function persist() {
  if (flushHandle) return;
  // Coalesce: this is called from a scroll listener, and serialising on every
  // frame would be the one thing that makes scrolling stutter.
  flushHandle = window.setTimeout(() => {
    flushHandle = 0;
    try {
      sessionStorage.setItem(KEY, JSON.stringify([...positions]));
    } catch {
      /* storage full or unavailable — in-memory still works */
    }
  }, 250);
}

/** Take ownership of scroll positioning from the browser. */
export function claimScrollRestoration() {
  if (typeof history !== "undefined" && "scrollRestoration" in history) {
    history.scrollRestoration = "manual";
  }
}

export function remember(key: string, y: number) {
  positions.set(key, y);
  persist();
}

export function positionFor(key: string): number | undefined {
  return positions.get(key);
}

/** Jump the window without animating, regardless of the global smooth rule. */
export function jumpTo(top: number) {
  const root = document.documentElement;
  const previous = root.style.scrollBehavior;
  root.style.scrollBehavior = "auto";
  window.scrollTo(0, top);
  root.style.scrollBehavior = previous;
}

/**
 * Put the reader where this navigation should start.
 *
 * Following a link starts at the top; Back and Forward return to where that
 * entry was left. Returns a cleanup that cancels any in-flight retry.
 *
 * The retry exists because a page is rarely its final height on the frame it
 * mounts — diagrams measure, sticky columns resolve — and until it is, the
 * browser clamps the offset to whatever the document currently allows. One
 * attempt restores 1078 of the 1400 you left at, which is worse than either
 * extreme because it looks deliberate. The deadline exists so a page that
 * genuinely cannot reach the offset stops fighting a reader who has already
 * started scrolling.
 */
export function settleScroll(key: string, navigationType: string): () => void {
  const remembered = positions.get(key);
  const isPop = navigationType === "POP";

  // A cold arrival: no recorded offset and nowhere to have come from. Nothing
  // to restore, and forcing the top would undo a deep link to an #anchor.
  if (isPop && remembered === undefined) return () => {};

  const target = isPop ? remembered! : 0;
  let raf = 0;
  const deadline = performance.now() + 300;

  const attempt = () => {
    jumpTo(target);
    if (Math.abs(window.scrollY - target) > 4 && performance.now() < deadline) {
      raf = requestAnimationFrame(attempt);
    }
  };
  attempt();

  return () => {
    if (raf) cancelAnimationFrame(raf);
  };
}
