import { test, expect } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";

test("clicking empty space retains focus on chat input", async ({
  page,
}, testInfo) => {
  await page.context().clearCookies();
  await loginAsWorkerUser(page, testInfo.workerIndex);
  await page.goto("/app");
  await page.waitForLoadState("networkidle");

  const textarea = page.locator("#onyx-chat-input-textarea");
  await textarea.waitFor({ state: "visible", timeout: 10000 });

  // Focus the textarea and type something
  await textarea.focus();
  await textarea.fill("test message");
  await expect(textarea).toBeFocused();

  // Click on the main container's empty space (top-left corner)
  const container = page.locator("[data-main-container]");
  await container.click({ position: { x: 10, y: 10 } });

  // Focus should remain on the textarea
  await expect(textarea).toBeFocused();
});

test("clicking interactive elements still moves focus away", async ({
  page,
}, testInfo) => {
  await page.context().clearCookies();
  await loginAsWorkerUser(page, testInfo.workerIndex);
  await page.goto("/app");
  await page.waitForLoadState("networkidle");

  const textarea = page.locator("#onyx-chat-input-textarea");
  await textarea.waitFor({ state: "visible", timeout: 10000 });

  // Focus the textarea
  await textarea.focus();
  await expect(textarea).toBeFocused();

  // Click on an interactive element inside the container
  const button = page.locator("[data-main-container] button").first();
  await button.waitFor({ state: "visible", timeout: 5000 });
  await button.click();

  // Focus should have moved away from the textarea
  await expect(textarea).not.toBeFocused();
});
