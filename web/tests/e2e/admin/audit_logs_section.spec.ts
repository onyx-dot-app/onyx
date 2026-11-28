import { expect, test } from "@tests/e2e/fixtures/eeFeatures";
import { loginAs } from "@tests/e2e/utils/auth";
import { AdminSecurityPage } from "@tests/e2e/pages/AdminSecurityPage";

test.describe("Audit Logs and SIEM section @exclusive", () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    // Signing in writes an auth.login audit event for the status card.
    await loginAs(page, "admin");
  });

  test("admin sees the docs link and status, and can turn on a category", async ({
    page,
    eeEnabled,
  }) => {
    test.skip(!eeEnabled, "Requires an active Enterprise license");
    const securityPage = new AdminSecurityPage(page);
    await securityPage.goto();

    await expect(securityPage.auditSectionTitle).toBeVisible();
    await expect(securityPage.auditDocsLink).toHaveAttribute(
      "href",
      new RegExp(`${AdminSecurityPage.AUDIT_DOCS_PATH}$`)
    );
    await expect(securityPage.auditStatusTitle).toBeVisible();
    await expect(securityPage.auditStatusSummary().first()).toBeVisible();

    const toggle = AdminSecurityPage.SEARCHES_TOGGLE;
    const initial = await securityPage.isToggleOn(toggle);
    try {
      await securityPage.clickToggleAndSave(toggle);
      await securityPage.reload();
      await securityPage.expectToggle(toggle, !initial);
    } finally {
      // Restore the original value, even when a check fails.
      await securityPage.reload();
      if ((await securityPage.isToggleOn(toggle)) !== initial) {
        await securityPage.clickToggleAndSave(toggle);
      }
    }
    await securityPage.expectToggle(toggle, initial);
  });
});
