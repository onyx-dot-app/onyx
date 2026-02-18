import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import { loginAsRandomUser } from "../utils/auth";
import { expectElementScreenshot } from "../utils/visualRegression";

async function sendMessageAndWaitForChat(page: Page, message: string) {
  await page.locator("#onyx-chat-input-textarea").click();
  await page.locator("#onyx-chat-input-textarea").fill(message);
  await page.locator("#onyx-chat-input-send-button").click();

  await page.waitForFunction(
    () => window.location.href.includes("chatId="),
    null,
    { timeout: 15000 }
  );

  await expect(page.locator('[aria-label="share-chat-button"]')).toBeVisible({
    timeout: 10000,
  });
}

async function openShareModal(page: Page) {
  await page.locator('[aria-label="share-chat-button"]').click();
  await expect(page.getByRole("dialog")).toBeVisible({ timeout: 5000 });
}

test.describe("Share Chat Session Modal", () => {
  test.describe.configure({ mode: "serial" });

  let page: Page;

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    await loginAsRandomUser(page);
    await sendMessageAndWaitForChat(page, "Hello for share test");
  });

  test.afterAll(async () => {
    await page.close();
  });

  test("shows Private selected by default", async () => {
    await openShareModal(page);

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    const privateOption = dialog.locator(
      '[aria-label="share-modal-option-private"]'
    );
    await expect(privateOption.locator("svg").last()).toBeVisible();

    const submitButton = dialog.locator('[aria-label="share-modal-submit"]');
    await expect(submitButton).toHaveText("Done");

    const cancelButton = dialog.locator('[aria-label="share-modal-cancel"]');
    await expect(cancelButton).toBeVisible();

    await expectElementScreenshot(dialog, {
      name: "share-modal-default-private",
    });

    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden({ timeout: 5000 });
  });

  test("selecting Your Organization changes submit text", async () => {
    await openShareModal(page);

    const dialog = page.getByRole("dialog");

    await dialog.locator('[aria-label="share-modal-option-public"]').click();

    const submitButton = dialog.locator('[aria-label="share-modal-submit"]');
    await expect(submitButton).toHaveText("Create Share Link");

    const cancelButton = dialog.locator('[aria-label="share-modal-cancel"]');
    await expect(cancelButton).toBeVisible();

    await expectElementScreenshot(dialog, {
      name: "share-modal-public-selected",
    });

    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden({ timeout: 5000 });
  });

  test("Cancel closes modal without API calls", async () => {
    let patchCallCount = 0;
    await page.route("**/api/chat/chat-session/*", async (route) => {
      if (route.request().method() === "PATCH") {
        patchCallCount++;
      }
      await route.continue();
    });

    await openShareModal(page);

    const dialog = page.getByRole("dialog");
    const cancelButton = dialog.locator('[aria-label="share-modal-cancel"]');
    await cancelButton.click();

    await expect(dialog).toBeHidden({ timeout: 5000 });
    expect(patchCallCount).toBe(0);

    await page.unrouteAll({ behavior: "ignoreErrors" });
  });

  test("X button closes modal without API calls", async () => {
    let patchCallCount = 0;
    await page.route("**/api/chat/chat-session/*", async (route) => {
      if (route.request().method() === "PATCH") {
        patchCallCount++;
      }
      await route.continue();
    });

    await openShareModal(page);

    const dialog = page.getByRole("dialog");
    const closeButton = dialog.locator('div[tabindex="-1"] button');
    await closeButton.click();

    await expect(dialog).toBeHidden({ timeout: 5000 });
    expect(patchCallCount).toBe(0);

    await page.unrouteAll({ behavior: "ignoreErrors" });
  });

  test("creating a share link calls API and shows link", async () => {
    await openShareModal(page);

    const dialog = page.getByRole("dialog");

    let patchBody: Record<string, unknown> | null = null;
    await page.route("**/api/chat/chat-session/*", async (route) => {
      if (route.request().method() === "PATCH") {
        patchBody = JSON.parse(route.request().postData() ?? "{}");
        await route.continue();
      } else {
        await route.continue();
      }
    });

    await dialog.locator('[aria-label="share-modal-option-public"]').click();
    const submitButton = dialog.locator('[aria-label="share-modal-submit"]');
    await submitButton.click();

    await page.waitForResponse(
      (r) =>
        r.url().includes("/api/chat/chat-session/") &&
        r.request().method() === "PATCH",
      { timeout: 10000 }
    );

    expect(patchBody).toEqual({ sharing_status: "public" });

    const linkInput = dialog.locator('[aria-label="share-modal-link-input"]');
    await expect(linkInput).toBeVisible({ timeout: 5000 });

    const inputValue = await linkInput.locator("input").inputValue();
    expect(inputValue).toContain("/app/shared/");

    await expect(submitButton).toHaveText("Copy Link");
    await expect(dialog.getByText("Chat shared")).toBeVisible();
    await expect(
      dialog.locator('[aria-label="share-modal-cancel"]')
    ).toBeHidden();

    await expectElementScreenshot(dialog, {
      name: "share-modal-link-created",
      mask: ['[aria-label="share-modal-link-input"]'],
    });

    await page.unrouteAll({ behavior: "ignoreErrors" });

    // Wait for the toast to confirm SWR data has been refreshed
    // before closing, so the next test sees up-to-date shared_status
    await expect(
      page.getByText("Share link copied to clipboard!").first()
    ).toBeVisible({ timeout: 5000 });

    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden({ timeout: 5000 });
  });

  test("Copy Link triggers clipboard copy", async () => {
    await openShareModal(page);

    const dialog = page.getByRole("dialog");

    await expect(
      dialog.locator('[aria-label="share-modal-link-input"]')
    ).toBeVisible({ timeout: 5000 });

    const submitButton = dialog.locator('[aria-label="share-modal-submit"]');
    await expect(submitButton).toHaveText("Copy Link");

    await submitButton.click();

    await expect(
      page.getByText("Share link copied to clipboard!").first()
    ).toBeVisible({ timeout: 5000 });

    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden({ timeout: 5000 });
  });

  test("making chat private again calls API and closes modal", async () => {
    let patchBody: Record<string, unknown> | null = null;
    await page.route("**/api/chat/chat-session/*", async (route) => {
      if (route.request().method() === "PATCH") {
        patchBody = JSON.parse(route.request().postData() ?? "{}");
        await route.continue();
      } else {
        await route.continue();
      }
    });

    await openShareModal(page);

    const dialog = page.getByRole("dialog");
    const submitButton = dialog.locator('[aria-label="share-modal-submit"]');

    await dialog.locator('[aria-label="share-modal-option-private"]').click();

    await expect(submitButton).toHaveText("Make Private");

    await submitButton.click();

    await page.waitForResponse(
      (r) =>
        r.url().includes("/api/chat/chat-session/") &&
        r.request().method() === "PATCH",
      { timeout: 10000 }
    );

    expect(patchBody).toEqual({ sharing_status: "private" });

    await expect(dialog).toBeHidden({ timeout: 5000 });

    await expect(page.getByText("Chat is now private")).toBeVisible({
      timeout: 5000,
    });

    await page.unrouteAll({ behavior: "ignoreErrors" });
  });
});
