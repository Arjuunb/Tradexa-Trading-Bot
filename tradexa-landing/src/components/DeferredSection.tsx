import { Suspense, useEffect, useRef, useState, type ReactNode } from "react";

/**
 * Mounts a landing section only once it is near the viewport.
 *
 * The landing page imported all seventeen sections eagerly into one 473KB
 * chunk, and the HTML shell carries no content at all — so nothing could paint
 * until the whole bundle had downloaded, parsed and executed. On a slow
 * connection that is several seconds of blank page followed by the Suspense
 * fallback (a small centred card) and only then the real page.
 *
 * Splitting alone would not have fixed it: a lazy component that renders
 * immediately requests its chunk immediately, so all seventeen would still be
 * in flight at once, just in more files. The section has to stay unmounted
 * until it is worth loading.
 *
 * `minHeight` reserves the space a section will occupy. Without it the page
 * would be one screen tall until things loaded, the scrollbar would jump as
 * each arrived, and anchor links would land in the wrong place.
 */
export function DeferredSection({
  children,
  minHeight = 520,
  rootMargin = "600px",
}: {
  children: ReactNode;
  /** Approximate rendered height, in px, used to reserve scroll space. */
  minHeight?: number;
  /** How far ahead of the viewport to start loading. Generous on purpose:
   *  the chunk should arrive before the section does, not while you look at it. */
  rootMargin?: string;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [show, setShow] = useState(false);

  useEffect(() => {
    if (show) return;
    const el = ref.current;
    // No IntersectionObserver (or no element) means we cannot tell what is
    // near the viewport — so render everything rather than risk a page that
    // never fills in.
    if (!el || typeof IntersectionObserver === "undefined") {
      setShow(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setShow(true);
          io.disconnect();
        }
      },
      { rootMargin },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [show, rootMargin]);

  return (
    <div ref={ref} style={show ? undefined : { minHeight }}>
      {show ? <Suspense fallback={<div style={{ minHeight }} />}>{children}</Suspense> : null}
    </div>
  );
}
