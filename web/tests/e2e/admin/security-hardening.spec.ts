import { test, expect } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";

test.describe("Security Hardening Page @exclusive", () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
  });

  test("admin can toggle a setting, reload, and see it persisted", async ({
    page,
  }) => {
    await page.goto("/admin/security");
    await page.waitForLoadState("networkidle");

    await expect(
      page.getByText("Restrict User Directory to Admins")
    ).toBeVisible({ timeout: 10000 });

    // Read initial state of the User Directory toggle.
    const toggleRow = page
      .getByText("Restrict User Directory to Admins")
      .locator("xpath=ancestor::label[1]");
    const switchEl = toggleRow.getByRole("switch");
    await expect(switchEl).toBeVisible();
    const initial = (await switchEl.getAttribute("aria-checked")) === "true";

    // Flip it.
    await switchEl.click();
    await expect(page.getByText("Security settings updated")).toBeVisible({
      timeout: 5000,
    });

    // Reload and confirm the flipped value persisted.
    await page.reload();
    await page.waitForLoadState("networkidle");
    const switchAfterReload = page
      .getByText("Restrict User Directory to Admins")
      .locator("xpath=ancestor::label[1]")
      .getByRole("switch");
    await expect(switchAfterReload).toHaveAttribute(
      "aria-checked",
      initial ? "false" : "true"
    );

    // Restore the original value.
    await switchAfterReload.click();
    await expect(page.getByText("Security settings updated")).toBeVisible({
      timeout: 5000,
    });
  });

});
