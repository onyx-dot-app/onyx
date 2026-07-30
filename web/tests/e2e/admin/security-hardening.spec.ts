import { test } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { AdminSecurityPage } from "@tests/e2e/pages/AdminSecurityPage";

test.describe("Security Hardening Page @exclusive", () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
  });

  test("admin can toggle a setting, reload, and see it persisted", async ({
    page,
  }) => {
    const securityPage = new AdminSecurityPage(page);
    await securityPage.goto();

    const toggle = AdminSecurityPage.SESSION_EXPIRY_TOGGLE;
    const initial = await securityPage.isToggleOn(toggle);

    // Flip it and confirm the save.
    await securityPage.clickToggleAndSave(toggle);

    // Reload and confirm the flipped value persisted.
    await securityPage.reload();
    await securityPage.expectToggle(toggle, !initial);

    // Restore the original value so the test leaves no residue.
    await securityPage.clickToggleAndSave(toggle);
    await securityPage.expectToggle(toggle, initial);
  });
});
