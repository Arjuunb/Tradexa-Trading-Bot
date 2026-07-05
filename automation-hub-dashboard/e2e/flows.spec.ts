import { test, expect } from "@playwright/test";
import { mockApi } from "./mock";

const NAV = [
  "Overview", "Markets", "Strategies", "Backtesting", "Simulation", "Replay",
  "Paper Trading", "Live Trading", "Portfolio", "Analytics", "AI Assistant",
  "Risk Manager", "Evolution", "Journal", "Logs", "Settings", "Safety Center",
];
const slug = (p: string) => p.toLowerCase().replace(/ /g, "-");

test("sidebar nav — every item navigates and marks itself active", async ({ page }) => {
  await mockApi(page);
  await page.goto("/#/overview");
  await page.waitForTimeout(500);

  for (const label of NAV) {
    const item = page.locator("aside.sidebar button.nav-item", { hasText: label });
    await item.click();
    await expect(page).toHaveURL(new RegExp(`#/${slug(label)}$`));
    await expect(item).toHaveClass(/active/);
  }
});

test("top bar icons navigate", async ({ page }) => {
  await mockApi(page);
  await page.goto("/#/overview");
  await page.getByLabel("Alerts").click();
  await expect(page).toHaveURL(/#\/alerts$/);
  await page.getByLabel("Settings").click();
  await expect(page).toHaveURL(/#\/settings$/);
});

test("Settings > Save Settings shows a success toast", async ({ page }) => {
  await mockApi(page);
  await page.goto("/#/settings");
  await page.waitForTimeout(800);
  const save = page.getByRole("button", { name: /Save Settings/i });
  await expect(save).toBeEnabled();
  await save.click();
  await expect(page.locator(".toast.success")).toBeVisible();
});

test("Change Password validates empty / short input", async ({ page }) => {
  await mockApi(page);
  await page.goto("/#/settings");
  await page.waitForTimeout(800);
  const btn = page.getByRole("button", { name: /Change password/i });
  await btn.scrollIntoViewIfNeeded();
  await btn.click();                                   // empty inputs
  await expect(page.locator(".toast.error")).toBeVisible();
});

test("Log out clears the session (POSTs /auth/logout)", async ({ page }) => {
  await mockApi(page);
  await page.goto("/#/settings");
  await page.waitForTimeout(800);
  const [req] = await Promise.all([
    page.waitForRequest((r) => r.url().includes("/auth/logout") && r.method() === "POST"),
    page.getByRole("button", { name: /Log out/i }).click(),
  ]);
  expect(req).toBeTruthy();
});

test("no unexpected 4xx/5xx from the app's own requests during a page tour", async ({ page }) => {
  await mockApi(page);
  const bad: string[] = [];
  page.on("response", (r) => {
    const u = r.url();
    if (u.includes(":8000") && r.status() >= 400) bad.push(`${r.status()} ${u}`);
  });
  for (const label of ["Overview", "Analytics", "Settings", "Risk Manager", "Evolution"]) {
    await page.goto(`/#/${slug(label)}`);
    await page.waitForTimeout(700);
  }
  expect(bad, bad.join("\n")).toHaveLength(0);
});

test("Journal page — lists journaled trades and expands the full decision journal", async ({ page }) => {
  await mockApi(page);
  await page.goto("/#/journal");
  await page.waitForTimeout(700);
  // page + a journaled trade row render
  await expect(page.getByRole("heading", { name: /Bot Trade Journal/i })).toBeVisible();
  await expect(page.locator("table.data-table").first()).toContainText("BTCUSDT");
  // expand the decision journal for that trade
  await page.getByRole("button", { name: /^View$/ }).first().click();
  await page.waitForTimeout(400);
  // the 9-section panel is now visible with real captured data + honesty markers
  await expect(page.getByText("1 · Trade Summary")).toBeVisible();
  await expect(page.getByText(/Not checked/).first()).toBeVisible();
  await expect(page.getByText(/never bypassed/i)).toBeVisible();
  // evolution memory table shows the staged setup
  await expect(page.getByText(/Evolution Memory/i)).toBeVisible();
  await expect(page.locator("table.data-table").last()).toContainText("early-signal");
});

test("Safety Center — live readiness is locked and the kill-switch test verifies", async ({ page }) => {
  await mockApi(page);
  await page.goto("/#/safety-center");
  await page.waitForTimeout(600);
  await expect(page.getByRole("heading", { name: /Live Trading Readiness/i })).toBeVisible();
  await expect(page.getByText("Live trading is LOCKED.")).toBeVisible();
  await expect(page.getByText(/Paper trading track record/)).toBeVisible();
  // kill-switch test: accept the confirm dialog, expect the verified toast
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: /Test Emergency Stop/i }).click();
  await expect(page.locator(".toast.success")).toBeVisible();
});

test("Logs — skipped trades are listed with failed gate and expandable snapshot", async ({ page }) => {
  await mockApi(page);
  await page.goto("/#/logs");
  await page.waitForTimeout(600);
  await expect(page.getByRole("heading", { name: /Skipped Trades/i })).toBeVisible();
  // the failed gate + reason render
  await expect(page.getByText("Max open positions (3) reached")).toBeVisible();
  // expand the market snapshot for the row that has one
  await page.getByRole("button", { name: /^View$/ }).first().click();
  await page.waitForTimeout(300);
  await expect(page.getByText(/regime/i).first()).toBeVisible();
});
