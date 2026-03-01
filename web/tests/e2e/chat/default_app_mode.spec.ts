import { test, expect } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

test.describe("Default App Mode", () => {
  test("loads persisted Search mode after refresh", async ({
    page,
  }, testInfo) => {
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const apiClient = new OnyxApiClient(page.request);
    await apiClient.setDefaultAppMode("SEARCH");

    // If Search mode is not available for this environment/user, the mode selector
    // is hidden and the app is forced to Chat mode.
    const restoreDefaultMode = async () => {
      await apiClient.setDefaultAppMode("CHAT");
    };

    try {
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      const appModeButton = page.getByLabel("Change app mode");
      await appModeButton.waitFor({ state: "visible", timeout: 10000 });
      await expect(appModeButton).toHaveText(/Search/);
    } finally {
      await restoreDefaultMode();
    }
  });
});
