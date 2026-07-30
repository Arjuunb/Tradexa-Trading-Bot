import { useEffect } from "react";

/**
 * Per-route document metadata.
 *
 * index.html carries one static title and description, which was correct when
 * the site was one document. With six real routes, every one of them would
 * otherwise be indexed — and shared into Slack, iMessage or a tweet — as
 * "TradeLogX Nexus | AI Trading Intelligence Platform" with landing-page copy.
 * This rewrites the title, description, canonical URL and the Open Graph /
 * Twitter pair on navigation, and puts them back when the page unmounts so a
 * route never leaks its metadata into the next one.
 */

const BRAND = "TradeLogX Nexus";
const ORIGIN = "https://www.trade-logx.com";

function upsertMeta(selector: string, attr: "name" | "property", key: string, content: string) {
  let el = document.head.querySelector<HTMLMetaElement>(selector);
  if (!el) {
    el = document.createElement("meta");
    el.setAttribute(attr, key);
    document.head.appendChild(el);
  }
  const previous = el.getAttribute("content");
  el.setAttribute("content", content);
  return previous;
}

function upsertCanonical(href: string) {
  let el = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');
  if (!el) {
    el = document.createElement("link");
    el.setAttribute("rel", "canonical");
    document.head.appendChild(el);
  }
  const previous = el.getAttribute("href");
  el.setAttribute("href", href);
  return previous;
}

export interface PageMeta {
  title: string;
  description: string;
  /** Route path, e.g. "/engine". Used for the canonical + og:url. */
  path: string;
}

export function usePageMeta({ title, description, path }: PageMeta) {
  useEffect(() => {
    const url = `${ORIGIN}${path}`;
    const fullTitle = `${title} | ${BRAND}`;

    const prevTitle = document.title;
    document.title = fullTitle;

    const restore: Array<() => void> = [];
    const set = (selector: string, attr: "name" | "property", key: string, value: string) => {
      const prev = upsertMeta(selector, attr, key, value);
      restore.push(() => {
        const el = document.head.querySelector<HTMLMetaElement>(selector);
        if (el && prev !== null) el.setAttribute("content", prev);
      });
    };

    set('meta[name="description"]', "name", "description", description);
    set('meta[property="og:title"]', "property", "og:title", fullTitle);
    set('meta[property="og:description"]', "property", "og:description", description);
    set('meta[property="og:url"]', "property", "og:url", url);
    set('meta[name="twitter:title"]', "name", "twitter:title", fullTitle);
    set('meta[name="twitter:description"]', "name", "twitter:description", description);

    const prevCanonical = upsertCanonical(url);

    return () => {
      document.title = prevTitle;
      restore.forEach((fn) => fn());
      if (prevCanonical) upsertCanonical(prevCanonical);
    };
  }, [title, description, path]);
}
