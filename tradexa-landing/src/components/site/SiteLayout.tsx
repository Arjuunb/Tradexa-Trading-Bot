import { Suspense, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigationType, useOutlet } from "react-router-dom";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { SiteNav } from "@/components/site/SiteNav";
import { SiteFooter } from "@/components/site/SiteFooter";
import { NAV_ROUTES, ACCENT_CLASSES, routeFor, prefetchRoute } from "@/site/routes";
import { settleScroll } from "@/site/scroll";
import { cn } from "@/lib/utils";

const EASE = [0.22, 1, 0.36, 1] as const;

/**
 * A skeleton sized like a page hero, shown while a route chunk arrives.
 *
 * The app-wide fallback is a full-page shell with its own header bar — under
 * this layout that would paint a second navbar beneath the real one for a few
 * hundred milliseconds. This one only stands in for the page body.
 */
function PageFallback() {
  return (
    <div className="container-x pt-40" aria-busy="true" aria-label="Loading page">
      <div className="h-3 w-28 rounded-full bg-white/[0.07]" />
      <div className="mt-6 h-12 w-3/4 max-w-2xl rounded-xl bg-white/[0.05]" />
      <div className="mt-3 h-12 w-1/2 max-w-xl rounded-xl bg-white/[0.04]" />
      <div className="mt-8 h-5 w-2/3 max-w-lg rounded-lg bg-white/[0.035]" />
      <div className="mt-14 h-72 w-full rounded-3xl bg-white/[0.025]" />
    </div>
  );
}

/**
 * Cross-page pager.
 *
 * Six sibling products with no path between them would make the navbar the
 * only way across, which reads as a directory rather than a tour. This gives
 * every page an explicit exit into the next one, tinted with that page's
 * accent so the destination announces itself before you arrive.
 */
function PagePager() {
  const { pathname } = useLocation();
  const index = NAV_ROUTES.findIndex((r) => r.path === pathname);
  if (index === -1) return null;

  const prev = index > 0 ? NAV_ROUTES[index - 1] : null;
  const next = index < NAV_ROUTES.length - 1 ? NAV_ROUTES[index + 1] : null;
  if (!prev && !next) return null;

  return (
    <nav aria-label="Page navigation" className="container-x pb-20 pt-4">
      <div className="grid gap-3 sm:grid-cols-2">
        {prev ? (
          <Link
            to={prev.path}
            onPointerEnter={() => prefetchRoute(prev.path)}
            onFocus={() => prefetchRoute(prev.path)}
            className={cn(
              "group relative overflow-hidden rounded-2xl border border-line bg-white/[0.02] p-5 transition-all duration-300 hover:-translate-y-0.5 hover:bg-white/[0.04]",
              ACCENT_CLASSES[prev.accent].hoverBorder,
            )}
          >
            <span className="flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-white/35">
              <ArrowLeft className="h-3.5 w-3.5 transition-transform group-hover:-translate-x-0.5" />
              Previous
            </span>
            <span className="mt-2 block text-lg font-semibold text-white">{prev.label}</span>
            <span className="mt-0.5 block text-sm text-white/45">{prev.blurb}</span>
            <span
              className={cn(
                "absolute inset-x-0 bottom-0 h-px opacity-0 transition-opacity group-hover:opacity-100",
                ACCENT_CLASSES[prev.accent].bg,
              )}
            />
          </Link>
        ) : (
          <span className="hidden sm:block" />
        )}

        {next && (
          <Link
            to={next.path}
            onPointerEnter={() => prefetchRoute(next.path)}
            onFocus={() => prefetchRoute(next.path)}
            className={cn(
              "group relative overflow-hidden rounded-2xl border border-line bg-white/[0.02] p-5 text-right transition-all duration-300 hover:-translate-y-0.5 hover:bg-white/[0.04]",
              ACCENT_CLASSES[next.accent].hoverBorder,
            )}
          >
            <span className="flex items-center justify-end gap-2 text-[11px] uppercase tracking-[0.18em] text-white/35">
              Next
              <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
            </span>
            <span className="mt-2 block text-lg font-semibold text-white">{next.label}</span>
            <span className="mt-0.5 block text-sm text-white/45">{next.blurb}</span>
            <span
              className={cn(
                "absolute inset-x-0 bottom-0 h-px opacity-0 transition-opacity group-hover:opacity-100",
                ACCENT_CLASSES[next.accent].bg,
              )}
            />
          </Link>
        )}
      </div>
    </nav>
  );
}

/**
 * Shared chrome for every dedicated product page.
 *
 * `useOutlet()` rather than `<Outlet/>` because AnimatePresence needs to hold
 * on to the *previous* element while it exits; `<Outlet/>` re-renders to the
 * new route immediately and the exit animation has nothing left to play.
 *
 * Scroll positioning is deferred until the crossfade finishes — see the
 * settle effect below for why the obvious timing does not work.
 */
export default function SiteLayout() {
  const location = useLocation();
  const navigationType = useNavigationType();
  const outlet = useOutlet();
  const reduced = useReducedMotion() ?? false;
  const mainRef = useRef<HTMLElement>(null);
  const route = routeFor(location.pathname);
  const accent = route ? ACCENT_CLASSES[route.accent] : ACCENT_CLASSES.gold;

  /**
   * When the new page is put in position.
   *
   * Recording offsets and the restore itself live in `@/site/scroll`, shared
   * with the routes that have no crossfade. What is specific here is the
   * *timing*: `onExitComplete` fires while the outgoing page is being removed
   * and before the incoming one has mounted, so restoring there finds a
   * document only as tall as the chrome and clamps the offset short. The
   * callback therefore only bumps a counter, and the work happens in a layout
   * effect — which by definition runs after the new page has committed.
   */
  const [settleKey, setSettleKey] = useState(0);
  const firstRun = useRef(true);

  // Reduced motion collapses the exit into a frame whose completion callback
  // can be skipped entirely, so the counter is bumped on route change too.
  useEffect(() => {
    if (reduced) setSettleKey((k) => k + 1);
  }, [location.key, reduced]);

  useLayoutEffect(() => {
    const cancel = settleScroll(location.key, navigationType);

    // Move focus into the new document, but never on the first paint: a page
    // that grabs focus the moment it loads is a page that has decided where
    // your cursor goes. On an in-app navigation it is the opposite — without
    // it a keyboard or screen-reader user stays parked in the navigation and
    // re-tabs through it on every page.
    if (!firstRun.current) mainRef.current?.focus({ preventScroll: true });
    firstRun.current = false;

    return cancel;
    // Only `settleKey`, and pointedly not `location.key`: keying on the
    // location fires this the instant the route changes, while the outgoing
    // page is still the mounted one. `settleKey` changes once the incoming
    // page has committed, and the closure already holds the new location.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settleKey]);

  return (
    <div className="relative min-h-screen">
      <a
        href="#site-main"
        className="sr-only left-4 top-4 z-[60] rounded-lg border border-line-strong bg-ink px-4 py-2 text-sm text-white focus:not-sr-only focus:absolute"
      >
        Skip to content
      </a>
      <SiteNav />

      <AnimatePresence mode="wait" initial={false} onExitComplete={() => setSettleKey((k) => k + 1)}>
        <motion.main
          key={location.pathname}
          id="site-main"
          ref={mainRef}
          // -1 makes it programmatically focusable without adding a stop in the
          // tab order; the outline is suppressed because the focus ring belongs
          // on controls, not on a whole page that was focused on your behalf.
          tabIndex={-1}
          className="outline-none"
          initial={reduced ? { opacity: 0 } : { opacity: 0, y: 12, filter: "blur(6px)" }}
          animate={reduced ? { opacity: 1 } : { opacity: 1, y: 0, filter: "blur(0px)" }}
          exit={reduced ? { opacity: 0 } : { opacity: 0, y: -8, filter: "blur(4px)" }}
          transition={{ duration: reduced ? 0.15 : 0.42, ease: EASE }}
        >
          <Suspense fallback={<PageFallback />}>{outlet}</Suspense>
        </motion.main>
      </AnimatePresence>

      {/* accent rule between the page body and the shared chrome */}
      <div
        aria-hidden
        className={cn("mx-auto h-px w-full max-w-7xl opacity-30 transition-colors duration-500", accent.bg)}
        style={{ maskImage: "linear-gradient(to right, transparent, black 30%, black 70%, transparent)" }}
      />
      <PagePager />
      <SiteFooter />
    </div>
  );
}
