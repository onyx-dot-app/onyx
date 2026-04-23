import { Page } from "@playwright/test";
import { test, expect } from "@tests/e2e/fixtures/eeFeatures";
import { loginAs } from "@tests/e2e/utils/auth";

async function expandAdvancedOptions(page: Page): Promise<void> {
  await expect(page.locator('[aria-label="admin-page-title"]')).toBeVisible({
    timeout: 10000,
  });

  const header = page.getByText("Advanced Options", { exact: true });
  await expect(header).toBeVisible({ timeout: 10000 });

  const queryHistoryTrigger = page
    .locator("label")
    .filter({ hasText: "Query History Visibility" })
    .first();

  const alreadyVisible = await queryHistoryTrigger
    .isVisible()
    .catch(() => false);
  if (alreadyVisible) return;

  await header.scrollIntoViewIfNeeded();
  await header.click();

  await expect(queryHistoryTrigger).toBeVisible({ timeout: 5000 });
}

async function getQueryHistoryValue(page: Page): Promise<string> {
  await expandAdvancedOptions(page);

  const trigger = page
    .locator("label")
    .filter({ hasText: "Query History Visibility" })
    .locator('[role="combobox"]');

  const text = (await trigger.textContent()) ?? "";
  for (const label of ["Show with User Info", "Anonymized", "Hidden"]) {
    if (text.includes(label)) return label;
  }
  return text;
}

async function setQueryHistoryType(
  page: Page,
  value: "Show with User Info" | "Anonymized" | "Hidden"
): Promise<void> {
  await page.goto("/admin/configuration/chat-preferences");
  await page.waitForLoadState("networkidle");
  await expandAdvancedOptions(page);

  const currentValue = await getQueryHistoryValue(page);
  if (currentValue === value) return;

  const trigger = page
    .locator("label")
    .filter({ hasText: "Query History Visibility" })
    .locator('[role="combobox"]');

  await trigger.scrollIntoViewIfNeeded();
  await trigger.click();

  const option = page.locator('[role="option"]').filter({ hasText: value });
  await expect(option).toBeVisible({ timeout: 3000 });
  await option.click();

  await expect(page.getByText("Settings updated")).toBeVisible({
    timeout: 5000,
  });
}

test.describe("Query History Toggle @exclusive", () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
  });

  test.afterEach(async ({ page }) => {
    await setQueryHistoryType(page, "Show with User Info");
  });

  test("dropdown shows current value and persists after reload", async ({
    page,
  }) => {
    await page.goto("/admin/configuration/chat-preferences");
    await page.waitForLoadState("networkidle");

    const currentValue = await getQueryHistoryValue(page);
    expect(["Show with User Info", "Anonymized", "Hidden"]).toContain(
      currentValue
    );

    await setQueryHistoryType(page, "Anonymized");

    await page.reload();
    await page.waitForLoadState("networkidle");

    const newValue = await getQueryHistoryValue(page);
    expect(newValue).toBe("Anonymized");
  });

  test("setting to Hidden hides query history sidebar link", async ({
    page,
    eeEnabled,
  }) => {
    test.skip(!eeEnabled, "Query History page requires enterprise license");

    await setQueryHistoryType(page, "Show with User Info");

    await page.goto("/admin/performance/usage");
    await page.waitForLoadState("networkidle");

    const sidebar = page.locator('[class*="group/SidebarWrapper"]');
    const queryHistoryLink = sidebar.locator(
      'a[href="/admin/performance/query-history"]'
    );
    await expect(queryHistoryLink).toBeVisible({ timeout: 5000 });

    await setQueryHistoryType(page, "Hidden");

    await page.goto("/admin/performance/usage");
    await page.waitForLoadState("networkidle");

    const sidebarAfter = page.locator('[class*="group/SidebarWrapper"]');
    const queryHistoryLinkAfter = sidebarAfter.locator(
      'a[href="/admin/performance/query-history"]'
    );
    await expect(queryHistoryLinkAfter).not.toBeVisible({ timeout: 5000 });
  });

  test("can cycle through all three options", async ({ page }) => {
    await setQueryHistoryType(page, "Show with User Info");
    await page.reload();
    await page.waitForLoadState("networkidle");
    expect(await getQueryHistoryValue(page)).toBe("Show with User Info");

    await setQueryHistoryType(page, "Anonymized");
    await page.reload();
    await page.waitForLoadState("networkidle");
    expect(await getQueryHistoryValue(page)).toBe("Anonymized");

    await setQueryHistoryType(page, "Hidden");
    await page.reload();
    await page.waitForLoadState("networkidle");
    expect(await getQueryHistoryValue(page)).toBe("Hidden");
  });
});
