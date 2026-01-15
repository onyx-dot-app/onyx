import { test, expect, Page } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

/** Upload a file through the inline manager, retrying on transient failures. */
async function uploadTestFile(
  page: Page,
  fileName: string,
  content: string,
  maxRetries: number = 3
): Promise<void> {
  const buffer = Buffer.from(content, "utf-8");

  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      const addFilesButton = page.getByRole("button", { name: /add files/i });
      await expect(addFilesButton).toBeVisible({ timeout: 5000 });
      await expect(addFilesButton).toBeEnabled({ timeout: 5000 });

      const fileChooserPromise = page.waitForEvent("filechooser", {
        timeout: 5000,
      });
      await addFilesButton.click();
      const fileChooser = await fileChooserPromise;
      await fileChooser.setFiles({
        name: fileName,
        mimeType: "text/plain",
        buffer: buffer,
      });
      await expect(page.getByText(fileName)).toBeVisible({ timeout: 5000 });
      return;
    } catch (error) {
      if (attempt === maxRetries) {
        throw error;
      }
      await page.waitForTimeout(1000);
    }
  }
}

test.describe("InlineFileManagement", () => {
  test.describe.configure({ retries: 2 });

  let testCcPairId: number | null = null;

  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");

    const apiClient = new OnyxApiClient(page);
    testCcPairId = await apiClient.createFileConnector(
      `Test File Connector ${Date.now()}`
    );
  });

  test.afterEach(async ({ page }) => {
    const apiClient = new OnyxApiClient(page);

    if (testCcPairId !== null) {
      try {
        await apiClient.deleteCCPair(testCcPairId);
        testCcPairId = null;
      } catch (error) {
        console.warn(
          `Failed to delete test connector ${testCcPairId}: ${error}`
        );
      }
    }
  });

  test("should display files section on connector page", async ({ page }) => {
    await page.goto(`/admin/connector/${testCcPairId}`);
    await page.waitForLoadState("networkidle");

    await expect(page.getByText(/Files \(/)).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole("button", { name: /edit/i })).toBeVisible();
  });

  test("should enter and exit edit mode", async ({ page }) => {
    await page.goto(`/admin/connector/${testCcPairId}`);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: /edit/i }).click();
    await expect(page.getByRole("button", { name: /cancel/i })).toBeVisible();
    await expect(
      page.getByRole("button", { name: /save changes/i })
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /add files/i })
    ).toBeVisible();
    await page.getByRole("button", { name: /cancel/i }).click();
    await expect(page.getByRole("button", { name: /edit/i })).toBeVisible();
  });

  test("should add files and show them as pending", async ({ page }) => {
    await page.goto(`/admin/connector/${testCcPairId}`);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: /edit/i }).click();
    await page.waitForTimeout(500);
    await uploadTestFile(
      page,
      "test-document.txt",
      "This is a test document content"
    );
    await expect(page.getByText("New")).toBeVisible();
    const saveButton = page.getByRole("button", { name: /save changes/i });
    await expect(saveButton).toBeEnabled();
  });

  test("should remove pending file before saving", async ({ page }) => {
    await page.goto(`/admin/connector/${testCcPairId}`);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: /edit/i }).click();
    await page.waitForTimeout(500);
    await uploadTestFile(
      page,
      "file-to-remove.txt",
      "This file will be removed"
    );
    const newFileRow = page.locator("tr", { hasText: "file-to-remove.txt" });
    await newFileRow.locator('button[title="Remove file"]').click();
    await expect(page.getByText("file-to-remove.txt")).not.toBeVisible();
  });

  test("should show confirmation modal when saving", async ({ page }) => {
    await page.goto(`/admin/connector/${testCcPairId}`);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: /edit/i }).click();
    await page.waitForTimeout(500);
    await uploadTestFile(
      page,
      "confirm-test.txt",
      "Test content for confirmation modal"
    );
    await page.getByRole("button", { name: /save changes/i }).click();
    const modalDialog = page.getByRole("dialog", {
      name: /confirm file changes/i,
    });
    await expect(modalDialog).toBeVisible({ timeout: 5000 });
    await expect(
      modalDialog.getByText(/1 file\(s\) will be added/)
    ).toBeVisible();
    await expect(
      modalDialog.getByRole("button", { name: /confirm & save/i })
    ).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(modalDialog).not.toBeVisible();
    await expect(
      page.getByRole("button", { name: /save changes/i })
    ).toBeVisible();
  });

  test("should cancel edit mode and discard changes", async ({ page }) => {
    await page.goto(`/admin/connector/${testCcPairId}`);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: /edit/i }).click();
    await page.waitForTimeout(500);
    await uploadTestFile(
      page,
      "discard-test.txt",
      "This file should be discarded"
    );
    await page.getByRole("button", { name: /cancel/i }).click();
    await expect(page.getByRole("button", { name: /edit/i })).toBeVisible();
    await expect(page.getByText("discard-test.txt")).not.toBeVisible();
  });
});
