import { test, expect } from "@playwright/test";
import { THEMES, setThemeBeforeNavigation } from "@tests/e2e/utils/theme";
import { expectElementScreenshot } from "@tests/e2e/utils/visualRegression";

const NON_EXISTENT_CHAT_ID = "00000000-0000-0000-0000-000000000000";

for (const theme of THEMES) {
  test.describe(`Chat session not found (${theme} mode)`, () => {
    test.beforeEach(async ({ page }) => {
      await setThemeBeforeNavigation(page, theme);
    });

    test("should show 404 page for a non-existent chat session", async ({
      page,
    }) => {
      await page.goto(`/app?chatId=${NON_EXISTENT_CHAT_ID}`);

      await expect(page.getByText("Chat not found")).toBeVisible({
        timeout: 10000,
      });
      await expect(
        page.getByText("This chat session doesn't exist or has been deleted.")
      ).toBeVisible();
      await expect(
        page.getByRole("link", { name: "Start a new chat" })
      ).toBeVisible();

      // Sidebar should still be visible
      await expect(page.getByTestId("AppSidebar/new-session")).toBeVisible();

      const container = page.locator("[data-main-container]");
      await expect(container).toBeVisible();
      await expectElementScreenshot(container, {
        name: `chat-session-not-found-${theme}`,
      });
    });

    test("should navigate to /app when clicking Start a new chat", async ({
      page,
    }) => {
      await page.goto(`/app?chatId=${NON_EXISTENT_CHAT_ID}`);

      await expect(page.getByText("Chat not found")).toBeVisible({
        timeout: 10000,
      });

      await page.getByRole("link", { name: "Start a new chat" }).click();
      await page.waitForLoadState("networkidle");

      await expect(page).toHaveURL("/app");
      await expect(page.getByText("Chat not found")).toBeHidden();
    });
  });
}
