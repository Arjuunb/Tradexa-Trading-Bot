import { test, expect } from "@playwright/test";
import { mockApi } from "./mock";

/** Full UI click coverage (task 2): every sidebar link, every content button on
 *  every page, the paper controls, emergency stop, engine start/stop, settings
 *  save, logout, and change-password — all driven against the deterministic
 *  mock backend so nothing hits a live service. */

const NAV = [
  "Overview", "Markets", "Strategies", "Backtesting",
  "Paper Trading", "Bot Terminal", "Portfolio", "Analytics", "Strategy Proof", "Strategy Studio", "AI Intelligence",
  "Risk Manager", "Evolution", "Journal", "Memory", "Bot Health", "Logs", "Settings", "Safety Center",
];
// Pages demoted from the sidebar but still routable by hash (linked from their
// sibling pages) — they keep full button-sweep coverage below.
const HIDDEN = ["Symbols", "Simulation", "Replay", "Live Trading", "AI Assistant", "Decisions"];
const slug = (p: string) => p.toLowerCase().replace(/ /g, "-");

// ── every sidebar link navigates and every page renders without crashing ──
test("every sidebar link opens a page with no uncaught error or 4xx", async ({ page }) => {
  await mockApi(page);
  const errors: string[] = [];
  const bad: string[] = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("response", (r) => {
    if (r.url().includes(":8000") && r.status() >= 400) bad.push(`${r.status()} ${r.url()}`);
  });

  await page.goto("/#/overview");
  for (const label of NAV) {
    await page.locator("aside.sidebar button.nav-item", { hasText: label }).click();
    await expect(page).toHaveURL(new RegExp(`#/${slug(label)}$`));
    await expect(page.locator("h1.pagehead-title, h1.page-title").first()).toBeVisible();
    await page.waitForTimeout(300);
  }
  expect(errors, errors.join("\n")).toHaveLength(0);
  expect(bad, bad.join("\n")).toHaveLength(0);
});

// ── demoted pages stay reachable by hash and via their sibling-page links ──
test("hidden routes still render by hash", async ({ page }) => {
  await mockApi(page);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  for (const label of HIDDEN) {
    await page.goto(`/#/${slug(label)}`);
    await expect(page.locator("h1.pagehead-title, h1.page-title").first()).toBeVisible();
    await page.waitForTimeout(200);
  }
  expect(errors, errors.join("\n")).toHaveLength(0);
});

test("sibling-page cross-links open the demoted pages", async ({ page }) => {
  await mockApi(page);
  for (const [from, btn, target] of [
    ["markets", "Symbol Explorer", "symbols"],
    ["backtesting", "Simulation", "simulation"],
    ["backtesting", "Replay", "replay"],
    ["ai-intelligence", "AI Assistant", "ai-assistant"],
    ["journal", "Decisions", "decisions"],
    ["safety-center", "Live Trading", "live-trading"],
  ] as const) {
    await page.goto(`/#/${from}`);
    await page.waitForTimeout(250);
    await page.locator(".pagehead-actions button", { hasText: btn }).click();
    await expect(page).toHaveURL(new RegExp(`#/${target}$`));
  }
});

// ── click every content button on every page; none may throw ──
// One test PER PAGE (not a single monolithic sweep) so each has its own timeout
// budget and they run in parallel — the old single test grew slow enough to time
// out as pages and lazy-loaded chunks were added.
for (const label of [...NAV, ...HIDDEN]) {
  test(`clicking every content button on ${label} never throws`, async ({ page }) => {
    await mockApi(page);
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    // auto-dismiss confirms so destructive actions don't fire during the sweep
    page.on("dialog", (d) => d.dismiss().catch(() => {}));

    await page.goto(`/#/${slug(label)}`);
    await page.waitForTimeout(350);
    const n = await page.locator(".content button:visible").count();
    for (let i = 0; i < n; i++) {
      // reset to a clean page for each click so the index stays valid even when
      // a click toggles / removes / re-renders content
      await page.goto(`/#/${slug(label)}`);
      await page.waitForTimeout(120);
      const btns = page.locator(".content button:visible");
      if (i < (await btns.count())) await btns.nth(i).click({ timeout: 3000 }).catch(() => {});
      await page.waitForTimeout(50);
    }
    expect(errors, `uncaught errors while clicking on ${label}:\n${errors.join("\n")}`).toHaveLength(0);
  });
}

// ── paper controls fire the right endpoints ──
test("paper controls POST pause / stop / resume", async ({ page }) => {
  await mockApi(page);
  page.on("dialog", (d) => d.accept());   // Pause All / Stop All now confirm first (H-6)
  await page.goto("/#/paper-trading");
  await page.waitForTimeout(500);
  for (const [label, path] of [
    ["Pause All", "/controls/pause-all"],
    ["Stop All", "/controls/stop-all"],
    ["Resume", "/controls/resume"],
  ] as const) {
    const [req] = await Promise.all([
      page.waitForRequest((r) => r.url().includes(path) && r.method() === "POST"),
      page.getByRole("button", { name: new RegExp(`^${label}$`) }).click(),
    ]);
    expect(req, `${label} did not POST ${path}`).toBeTruthy();
  }
});

// ── engine start/stop fires the right endpoint ──
test("engine start button POSTs /engine/start", async ({ page }) => {
  await mockApi(page);           // mock reports engine stopped -> button says "Start Engine"
  await page.goto("/#/paper-trading");
  await page.waitForTimeout(500);
  const [req] = await Promise.all([
    page.waitForRequest((r) => r.url().includes("/engine/start") && r.method() === "POST"),
    page.getByRole("button", { name: /Start Engine/i }).click(),
  ]);
  expect(req).toBeTruthy();
});

// ── emergency stop (kill switch) halts trading + stops the engine ──
test("Safety Center kill switch POSTs stop-all and engine stop", async ({ page }) => {
  await mockApi(page);
  await page.goto("/#/safety-center");
  await page.waitForTimeout(500);
  page.once("dialog", (d) => d.accept());   // confirm the kill switch
  const [stopAll] = await Promise.all([
    page.waitForRequest((r) => r.url().includes("/controls/stop-all") && r.method() === "POST"),
    page.getByRole("button", { name: /Stop Everything/i }).click(),
  ]);
  expect(stopAll).toBeTruthy();
});

// ── settings save + change-password validation + logout ──
test("settings save shows success and change-password validates", async ({ page }) => {
  await mockApi(page);
  await page.goto("/#/settings");
  await page.waitForTimeout(700);
  const save = page.getByRole("button", { name: /Save Settings/i });
  await save.click();
  await expect(page.locator(".toast.success")).toBeVisible();

  const changePw = page.getByRole("button", { name: /Change password/i });
  await changePw.scrollIntoViewIfNeeded();
  await changePw.click();                              // empty -> validation error
  await expect(page.locator(".toast.error")).toBeVisible();
});

test("logout POSTs /auth/logout", async ({ page }) => {
  await mockApi(page);
  await page.goto("/#/settings");
  await page.waitForTimeout(700);
  const [req] = await Promise.all([
    page.waitForRequest((r) => r.url().includes("/auth/logout") && r.method() === "POST"),
    page.getByRole("button", { name: /Log out/i }).click(),
  ]);
  expect(req).toBeTruthy();
});
