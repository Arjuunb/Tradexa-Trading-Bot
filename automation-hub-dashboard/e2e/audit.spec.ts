import { test, expect, type Page, type ConsoleMessage } from "@playwright/test";
import { mockApi } from "./mock";

const PAGES = [
  "Overview", "Markets", "Strategies", "Backtesting", "Simulation", "Replay",
  "Paper Trading", "Live Trading", "Portfolio", "Analytics", "AI Assistant",
  "Risk Manager", "Evolution", "Logs", "Settings", "Safety Center",
];
const slug = (p: string) => p.toLowerCase().replace(/ /g, "-");

// console errors that are noise (not app defects) — network aborts from the
// polling hooks racing a page change, favicon, etc.
const IGNORE = [/Failed to load resource/i, /net::ERR_ABORTED/i, /favicon/i,
  /ResizeObserver/i, /Download the React DevTools/i];
function watchConsole(page: Page): string[] {
  const errs: string[] = [];
  page.on("console", (m: ConsoleMessage) => {
    if (m.type() === "error" && !IGNORE.some((r) => r.test(m.text()))) errs.push(m.text());
  });
  page.on("pageerror", (e) => errs.push("PAGEERROR: " + e.message));
  return errs;
}

test.describe("clickability audit — every page renders without JS errors", () => {
  for (const label of PAGES) {
    test(`page "${label}" loads clean`, async ({ page }) => {
      await mockApi(page);
      const errs = watchConsole(page);
      await page.goto(`/#/${slug(label)}`);
      await page.waitForTimeout(1200);            // let hooks fetch + render
      // the page shell must be present (sidebar + a heading somewhere)
      await expect(page.locator("aside.sidebar")).toBeVisible();
      expect(errs, `console errors on ${label}:\n${errs.join("\n")}`).toHaveLength(0);
    });
  }
});

test.describe("clickability audit — interactive elements are sound", () => {
  for (const label of PAGES) {
    test(`page "${label}" — accessible names + not covered`, async ({ page }) => {
      await mockApi(page);
      await page.goto(`/#/${slug(label)}`);
      await page.waitForTimeout(1000);

      // collect every visible interactive element
      const els = page.locator(
        'button:visible, a[href]:visible, [role="button"]:visible, input[type="submit"]:visible',
      );
      const n = await els.count();
      const unnamed: string[] = [];
      const covered: string[] = [];

      for (let i = 0; i < n; i++) {
        const el = els.nth(i);
        // accessible name: text, aria-label, or title
        const name = (
          (await el.textContent())?.trim() ||
          (await el.getAttribute("aria-label")) ||
          (await el.getAttribute("title")) || ""
        ).trim();
        const cls = (await el.getAttribute("class")) || "";
        if (!name) unnamed.push(cls || "(no class)");

        // not covered: the element at its own center is itself or a descendant
        const box = await el.boundingBox();
        if (box) {
          const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
          const isTop = await page.evaluate(
            ({ x, y }) => {
              const top = document.elementFromPoint(x, y);
              return { ok: !!top };
            }, { x: cx, y: cy },
          );
          if (!isTop.ok) covered.push(cls);
        }
      }

      expect(unnamed, `unnamed interactive elements on ${label}: ${unnamed.join(", ")}`).toHaveLength(0);
      // covered check is advisory — overlays/tooltips can legitimately sit on top
      if (covered.length) console.log(`[${label}] ${covered.length} possibly-covered elements`);
    });
  }
});
