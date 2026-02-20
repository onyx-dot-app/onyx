import { test, expect, Page } from "@playwright/test";
import { loginAsRandomUser } from "@tests/e2e/utils/auth";

/**
 * E2E test to verify user files are properly attached to assistants.
 *
 * This test prevents a regression where user_file_ids were not being saved
 * when creating an assistant, causing uploaded files to not be associated
 * with the persona in the database.
 */

// --- Locator Helper Functions ---
const getNameInput = (page: Page) => page.locator('input[name="name"]');
const getDescriptionInput = (page: Page) =>
  page.locator('textarea[name="description"]');
const getInstructionsTextarea = (page: Page) =>
  page.locator('textarea[name="instructions"]');
const getKnowledgeToggle = (page: Page) =>
  page.locator('button[role="switch"][name="enable_knowledge"]');
const getCreateSubmitButton = (page: Page) =>
  page.locator('button[type="submit"]:has-text("Create")');

const extractAssistantIdFromCreateResponse = (
  payload: Record<string, unknown> | null
): number | null => {
  if (!payload) {
    return null;
  }
  const rawId = payload.id ?? payload.assistant_id ?? payload.persona_id;
  if (typeof rawId === "number" && Number.isFinite(rawId)) {
    return rawId;
  }
  if (typeof rawId === "string") {
    const parsed = Number(rawId);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return null;
};

const createAssistantAndGetId = async (page: Page): Promise<number> => {
  const createResponsePromise = page.waitForResponse(
    (response) => {
      if (response.request().method() !== "POST" || !response.ok()) {
        return false;
      }
      try {
        const pathname = new URL(response.url()).pathname;
        return /^\/api\/persona\/?$/.test(pathname);
      } catch {
        return false;
      }
    },
    { timeout: 30000 }
  );

  await getCreateSubmitButton(page).click();

  const createResponse = await createResponsePromise;

  await page.waitForURL(
    (url) => {
      const href = typeof url === "string" ? url : url.toString();
      return /\/app\?assistantId=\d+/.test(href) || /\/app\?chatId=/.test(href);
    },
    { timeout: 20000 }
  );

  const assistantIdFromUrl = page.url().match(/assistantId=(\d+)/);
  if (assistantIdFromUrl?.[1]) {
    return Number(assistantIdFromUrl[1]);
  }

  const createPayload = (await createResponse
    .json()
    .catch(() => null)) as Record<string, unknown> | null;
  const assistantIdFromResponse =
    extractAssistantIdFromCreateResponse(createPayload);
  if (assistantIdFromResponse !== null) {
    return assistantIdFromResponse;
  }

  throw new Error(
    `Assistant ID missing from URL (${page.url()}) and create response payload`
  );
};

// Helper to navigate to files view in the Knowledge UI
const navigateToFilesView = async (page: Page) => {
  // Check if we need to click "View / Edit" or "Add" button to open the knowledge panel
  const viewEditButton = page.getByLabel("knowledge-view-edit");
  const addButton = page.getByLabel("knowledge-add-button");

  if (await viewEditButton.isVisible()) {
    await viewEditButton.click();
  } else if (await addButton.isVisible()) {
    await addButton.click();
  }

  // Click on "Your Files" in the add view or sidebar
  const filesButton = page.getByLabel("knowledge-add-files");
  if (await filesButton.isVisible()) {
    await filesButton.click();
  } else {
    // Try the sidebar version
    const sidebarFiles = page.getByLabel("knowledge-sidebar-files");
    if (await sidebarFiles.isVisible()) {
      await sidebarFiles.click();
    }
  }

  // Wait for the files table to appear
  await page.waitForTimeout(500);
};

// Helper to upload a file through the knowledge panel
async function uploadTestFile(
  page: Page,
  fileName: string,
  content: string,
  maxRetries: number = 3
): Promise<string> {
  const buffer = Buffer.from(content, "utf-8");

  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      console.log(`[test] Upload attempt ${attempt} for ${fileName}`);

      // Find the Add File button
      const addFileButton = page.getByRole("button", { name: /add file/i });
      await expect(addFileButton).toBeVisible({ timeout: 5000 });
      await expect(addFileButton).toBeEnabled({ timeout: 5000 });

      // Set up file chooser listener before clicking
      const fileChooserPromise = page.waitForEvent("filechooser", {
        timeout: 5000,
      });
      await addFileButton.click();
      const fileChooser = await fileChooserPromise;

      // Wait for upload API completion to avoid racing the UI refresh.
      const uploadResponsePromise = page.waitForResponse(
        (response) =>
          response.url().includes("/api/user/projects/file/upload") &&
          response.request().method() === "POST",
        { timeout: 15000 }
      );

      // Upload the file
      await fileChooser.setFiles({
        name: fileName,
        mimeType: "text/plain",
        buffer: buffer,
      });
      const uploadResponse = await uploadResponsePromise;
      expect(uploadResponse.ok()).toBeTruthy();

      // Wait for network to settle after upload
      await page.waitForLoadState("networkidle", { timeout: 10000 });

      // Wait a moment for the UI to update
      await page.waitForTimeout(500);

      // Wait for the uploaded file row to appear.
      const fileRow = page
        .locator('[aria-label^="user-file-row-"]')
        .filter({ hasText: fileName })
        .first();
      await expect(fileRow).toBeVisible({ timeout: 10000 });

      console.log(`[test] Successfully uploaded ${fileName}`);

      // Return the file name for verification later
      return fileName;
    } catch (error) {
      console.log(
        `[test] Upload attempt ${attempt} failed: ${
          error instanceof Error ? error.message : "unknown error"
        }`
      );
      if (attempt === maxRetries) {
        throw error;
      }
      await page.waitForTimeout(1000);
    }
  }

  throw new Error(
    `Failed to upload file ${fileName} after ${maxRetries} attempts`
  );
}

// Helper to select a file by clicking its row
async function selectFileByName(page: Page, fileName: string): Promise<void> {
  const fileNameWithoutExt = fileName.replace(".txt", "");

  // Try to find and click the row containing the file name
  // First try by aria-label
  let fileRow = page.locator(`[aria-label^="user-file-row-"]`, {
    has: page.locator(`text=${fileNameWithoutExt}`),
  });

  if ((await fileRow.count()) === 0) {
    // Fall back to finding by table-row-layout class
    fileRow = page.locator("[data-selected]", {
      has: page.locator(`text=${fileNameWithoutExt}`),
    });
  }

  if ((await fileRow.count()) === 0) {
    // Last resort: find any clickable row with the file name
    fileRow = page
      .locator("div", {
        has: page.locator(`text=${fileNameWithoutExt}`),
      })
      .filter({
        has: page.locator('[role="checkbox"], input[type="checkbox"]'),
      })
      .first();
  }

  if ((await fileRow.count()) > 0) {
    await fileRow.click();
  } else {
    // Just click on the file name text itself
    await page.locator(`text=${fileNameWithoutExt}`).first().click();
  }

  // Wait for the selection to register
  await page.waitForTimeout(300);
  console.log(`[test] Selected file: ${fileName}`);
}

test.describe("User File Attachment to Assistant", () => {
  // Run serially to avoid session conflicts between parallel workers
  test.describe.configure({ mode: "serial", retries: 1 });

  test("should persist user file attachment after creating assistant", async ({
    page,
  }: {
    page: Page;
  }) => {
    // Login as a random user (no admin needed for user files)
    await page.context().clearCookies();
    await loginAsRandomUser(page);

    const assistantName = `User File Test ${Date.now()}`;
    const assistantDescription = "Testing user file persistence";
    const assistantInstructions = "Help users with their uploaded files.";
    const testFileName = `test-file-${Date.now()}.txt`;
    const testFileContent =
      "This is test content for the user file attachment test.";

    // Navigate to assistant creation page
    await page.goto("/app/agents/create");
    await page.waitForLoadState("networkidle");

    // Fill in basic assistant details
    await getNameInput(page).fill(assistantName);
    await getDescriptionInput(page).fill(assistantDescription);
    await getInstructionsTextarea(page).fill(assistantInstructions);

    // Enable Knowledge toggle
    const knowledgeToggle = getKnowledgeToggle(page);
    await knowledgeToggle.scrollIntoViewIfNeeded();
    await expect(knowledgeToggle).toHaveAttribute("aria-checked", "false");
    await knowledgeToggle.click();
    await expect(knowledgeToggle).toHaveAttribute("aria-checked", "true");

    // Navigate to files view in the Knowledge UI
    await navigateToFilesView(page);

    // Upload a test file - this automatically adds it to user_file_ids
    await uploadTestFile(page, testFileName, testFileContent);

    // NOTE: We do NOT call selectFileByName here because uploadTestFile
    // already adds the file to user_file_ids. Clicking again would toggle it OFF.

    // Verify file appears in the UI (use first() since file may appear in multiple places)
    const fileText = page.getByText(testFileName).first();
    await expect(fileText).toBeVisible();

    // Submit the assistant creation form and resolve assistant ID from URL or API response.
    const assistantId = await createAssistantAndGetId(page);

    console.log(
      `[test] Created assistant ${assistantName} with ID ${assistantId}, now verifying file persistence...`
    );

    // Navigate to the edit page for the assistant
    await page.goto(`/app/agents/edit/${assistantId}`);
    await page.waitForURL(`**/app/agents/edit/${assistantId}`);
    await page.waitForLoadState("networkidle");

    // Verify knowledge toggle is still enabled
    await expect(getKnowledgeToggle(page)).toHaveAttribute(
      "aria-checked",
      "true"
    );

    // Navigate to files view
    await navigateToFilesView(page);

    // Wait for files to load
    await page.waitForTimeout(1000);

    // Verify the uploaded file still appears and is selected
    const fileNameWithoutExt = testFileName.replace(".txt", "");
    const fileTextAfterEdit = page
      .locator(`text=${fileNameWithoutExt}`)
      .first();
    await expect(fileTextAfterEdit).toBeVisible({ timeout: 10000 });

    // Wait for UI to fully render the selection state
    await page.waitForTimeout(500);

    // Verify the file row has data-selected="true" (indicating it's attached to the assistant)
    // This confirms: user_file_ids were saved when creating the assistant,
    // and they're correctly loaded and displayed when editing
    const fileRowAfterEdit = page.locator("[data-selected='true']", {
      has: page.locator(`text=${fileNameWithoutExt}`),
    });

    await expect(fileRowAfterEdit).toBeVisible({ timeout: 5000 });

    console.log(
      `[test] Successfully verified user file ${testFileName} is persisted and selected for assistant ${assistantName}`
    );
  });

  test("should persist multiple user files after editing assistant", async ({
    page,
  }: {
    page: Page;
  }) => {
    // Login as a random user
    await page.context().clearCookies();
    await loginAsRandomUser(page);

    const assistantName = `Multi-File Test ${Date.now()}`;
    const testFileName1 = `test-file-1-${Date.now()}.txt`;
    const testFileName2 = `test-file-2-${Date.now()}.txt`;
    const testFileContent = "Test content for multi-file test.";

    // Navigate to assistant creation page
    await page.goto("/app/agents/create");
    await page.waitForLoadState("networkidle");

    // Fill in basic assistant details
    await getNameInput(page).fill(assistantName);
    await getDescriptionInput(page).fill("Testing multiple user files");
    await getInstructionsTextarea(page).fill("Help with multiple files.");

    // Enable Knowledge toggle
    const knowledgeToggle = getKnowledgeToggle(page);
    await knowledgeToggle.scrollIntoViewIfNeeded();
    await knowledgeToggle.click();

    // Navigate to files view
    await navigateToFilesView(page);

    // Upload first file - automatically adds to user_file_ids
    await uploadTestFile(page, testFileName1, testFileContent);

    // Upload second file - automatically adds to user_file_ids
    await uploadTestFile(page, testFileName2, testFileContent);

    // NOTE: We do NOT call selectFileByName because uploadTestFile
    // already adds files to user_file_ids. Clicking would toggle them OFF.

    // Create the assistant and resolve assistant ID from URL or API response.
    const assistantId = await createAssistantAndGetId(page);

    // Go to edit page
    await page.goto(`/app/agents/edit/${assistantId}`);
    await page.waitForLoadState("networkidle");

    // Navigate to files view
    await navigateToFilesView(page);

    // Wait for files to load
    await page.waitForTimeout(1000);

    // Verify both files are visible and selected
    // This confirms: user_file_ids were saved when creating the assistant,
    // and they're correctly loaded and displayed when editing
    for (const fileName of [testFileName1, testFileName2]) {
      const fileNameWithoutExt = fileName.replace(".txt", "");
      const fileText = page.locator(`text=${fileNameWithoutExt}`).first();
      await expect(fileText).toBeVisible({ timeout: 10000 });

      // Verify the file is selected (data-selected="true")
      const fileRow = page.locator("[data-selected='true']", {
        has: page.locator(`text=${fileNameWithoutExt}`),
      });
      await expect(fileRow).toBeVisible({ timeout: 5000 });
    }

    console.log(
      `[test] Successfully verified multiple user files are persisted for assistant ${assistantName}`
    );
  });
});
