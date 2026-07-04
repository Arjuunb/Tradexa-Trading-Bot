import { test, expect } from "@playwright/test";
import { mockApi } from "./mock";

const NAV = [
  "Overview", "Markets", "Strategies", "Backtesting", "Simulation", "Replay",
  "Paper Trading", "Live Trading", "Portfolio", "Analytics", "AI Assistant",
  "Risk Manager", "Evolution", "Logs", "Settings", "Safety Center",
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
