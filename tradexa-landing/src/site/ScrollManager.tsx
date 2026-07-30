import { useEffect, useLayoutEffect } from "react";
import { useLocation, useNavigationType } from "react-router-dom";
import { claimScrollRestoration, remember, settleScroll } from "./scroll";
import { isSitePath } from "./routes";

/**
 * Records scroll position for every route, and restores it for the ones that
 * have no transition of their own.
 *
 * Recording lives here rather than in a layout because it has to cover the
 * landing page and the settings tree too — a reader who scrolls halfway down
 * the landing page, opens /engine and comes back should land where they were,
 * and the landing page does not share the product-page chrome.
 *
 * Restoring is split: pages under SiteLayout have a crossfade, and putting
 * them in position before the incoming page has mounted is what makes the
 * offset clamp short, so SiteLayout calls `settleScroll` itself once its
 * transition completes. Everything else can be positioned immediately.
 */
export function ScrollManager() {
  const location = useLocation();
  const navigationType = useNavigationType();

  useEffect(claimScrollRestoration, []);

  useEffect(() => {
    const key = location.key;
    const onScroll = () => remember(key, window.scrollY);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [location.key]);

  useLayoutEffect(() => {
    if (isSitePath(location.pathname)) return;
    return settleScroll(location.key, navigationType);
    // navigationType is a property of this navigation, not an input that should
    // re-trigger positioning on its own.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.key]);

  return null;
}
