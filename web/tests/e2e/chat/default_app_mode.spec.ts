import { test, expect } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

test.describe("Default App Mode", () => {
  test("loads persisted Search mode after refresh", async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");

    // Arrange
    const apiClient = new OnyxApiClient(page.request);
    const ccPairId = await apiClient.createFileConnector(
      "Default App Mode Test Connector"
    );
    await apiClient.setDefaultAppMode("SEARCH");

    try {
      // Act
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      // Assert
      const appModeButton = page.getByLabel("Change app mode");
      await appModeButton.waitFor({ state: "visible", timeout: 10000 });
      await expect(appModeButton).toHaveText(/Search/);
    } finally {
      await apiClient.setDefaultAppMode("CHAT");
      await apiClient.deleteCCPair(ccPairId);
    }
  });
});
