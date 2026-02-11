import { test, expect, Page, Browser } from "@playwright/test";
import { loginAs, loginAsRandomUser } from "../utils/auth";
import { OnyxApiClient } from "../utils/onyxApiClient";

// --- Locator Helper Functions ---
const getNameInput = (page: Page) => page.locator('input[name="name"]');
const getDescriptionInput = (page: Page) =>
  page.locator('textarea[name="description"]');
const getInstructionsTextarea = (page: Page) =>
  page.locator('textarea[name="instructions"]');
const getReminderTextarea = (page: Page) =>
  page.locator('textarea[name="reminders"]');
const getKnowledgeToggle = (page: Page) =>
  page.locator('button[role="switch"][name="enable_knowledge"]');

// Helper function to set date using InputDatePicker (sets to today's date)
const setKnowledgeCutoffDate = async (page: Page) => {
  // Find and click the date picker button within the Knowledge Cutoff Date section
  const datePickerButton = page
    .locator('label:has-text("Knowledge Cutoff Date")')
    .locator("..")
    .locator('button:has-text("Select Date"), button:has-text("/")');

  await datePickerButton.click();

  // Wait for the popover to open
  await page.waitForSelector('[role="dialog"]', {
    state: "visible",
    timeout: 5000,
  });

  // Click the "Today" button to set to today's date
  const todayButton = page
    .locator('[role="dialog"]')
    .getByRole("button", { name: "Today" })
    .first();
  await todayButton.click();

  // The popover should close automatically after selection
  await page.waitForSelector('[role="dialog"]', {
    state: "hidden",
    timeout: 5000,
  });
};
const getStarterMessageInput = (page: Page, index: number = 0) =>
  page.locator(`input[name="starter_messages.${index}"]`);
const getCreateSubmitButton = (page: Page) =>
  page.locator('button[type="submit"]:has-text("Create")');
const getUpdateSubmitButton = (page: Page) =>
  page.locator('button[type="submit"]:has-text("Save")');

// Helper to navigate to document sets view in the new Knowledge UI
const navigateToDocumentSetsView = async (page: Page) => {
  // First, check if we need to click "View / Edit" or "Add" button to open the knowledge panel
  const viewEditButton = page.getByLabel("knowledge-view-edit");
  const addButton = page.getByLabel("knowledge-add-button");

  if (await viewEditButton.isVisible()) {
    await viewEditButton.click();
  } else if (await addButton.isVisible()) {
    await addButton.click();
  }

  // Now click on "Document Sets" in the add view or sidebar
  const documentSetsButton = page.getByLabel("knowledge-add-document-sets");
  if (await documentSetsButton.isVisible()) {
    await documentSetsButton.click();
  } else {
    // Try the sidebar version
    const sidebarDocumentSets = page.getByLabel(
      "knowledge-sidebar-document-sets"
    );
    if (await sidebarDocumentSets.isVisible()) {
      await sidebarDocumentSets.click();
    }
  }

  // Wait for the document sets table to appear
  await page.waitForTimeout(500);
};

// Helper to select a document set by ID in the new Knowledge UI
const selectDocumentSet = async (page: Page, documentSetId: number) => {
  const documentSetRow = page.getByLabel(`document-set-row-${documentSetId}`);
  await expect(documentSetRow).toBeVisible({ timeout: 5000 });
  await documentSetRow.click();
};

// Helper to navigate to files view in the new Knowledge UI
const navigateToFilesView = async (page: Page) => {
  // First, check if we need to click "View / Edit" or "Add" button to open the knowledge panel
  const viewEditButton = page.getByLabel("knowledge-view-edit");
  const addButton = page.getByLabel("knowledge-add-button");

  if (await viewEditButton.isVisible()) {
    await viewEditButton.click();
  } else if (await addButton.isVisible()) {
    await addButton.click();
  }

  // Now click on "Your Files" in the add view or sidebar
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

test.describe("Assistant Creation and Edit Verification", () => {
  // Configure this entire suite to run serially
  test.describe.configure({ mode: "serial" });

  test.describe("User Files Only", () => {
    test("should create assistant with user files when no connectors exist @exclusive", async ({
      page,
    }: {
      page: Page;
    }) => {
      await page.context().clearCookies();
      await loginAsRandomUser(page);

      const assistantName = `User Files Test ${Date.now()}`;
      const assistantDescription =
        "Testing user file uploads without connectors";
      const assistantInstructions = "Help users with their documents.";

      await page.goto("/app/agents/create");

      // Fill in basic assistant details
      await getNameInput(page).fill(assistantName);
      await getDescriptionInput(page).fill(assistantDescription);
      await getInstructionsTextarea(page).fill(assistantInstructions);

      // Enable Knowledge toggle
      const knowledgeToggle = getKnowledgeToggle(page);
      await knowledgeToggle.scrollIntoViewIfNeeded();
      await expect(knowledgeToggle).toHaveAttribute("aria-checked", "false");
      await knowledgeToggle.click();

      // Navigate to files view in the new Knowledge UI
      await navigateToFilesView(page);

      // Verify "Add File" button is visible in the new UI
      const addFileButton = page.getByRole("button", {
        name: /add file/i,
      });
      await expect(addFileButton).toBeVisible();

      // Submit the assistant creation form
      await getCreateSubmitButton(page).click();

      // Verify redirection to chat page with the new assistant
      await page.waitForURL(/.*\/app\?assistantId=\d+.*/);
      const url = page.url();
      const assistantIdMatch = url.match(/assistantId=(\d+)/);
      expect(assistantIdMatch).toBeTruthy();

      console.log(
        `[test] Successfully created assistant without connectors: ${assistantName}`
      );
    });
  });

  test.describe("With Knowledge", () => {
    let ccPairId: number;
    let documentSetId: number;

    test.afterAll(async ({ browser }: { browser: Browser }) => {
      // Cleanup using browser fixture (worker-scoped) to avoid per-test fixture limitation
      if (ccPairId && documentSetId) {
        const context = await browser.newContext({
          storageState: "admin_auth.json",
        });
        const page = await context.newPage();
        const cleanupClient = new OnyxApiClient(page.request);
        await cleanupClient.deleteDocumentSet(documentSetId);
        await cleanupClient.deleteCCPair(ccPairId);
        await context.close();
        console.log(
          "[test] Cleanup completed - deleted connector and document set"
        );
      }
    });

    test("should create and edit assistant with Knowledge enabled", async ({
      page,
    }: {
      page: Page;
    }) => {
      // Login as admin to create connector and document set (requires admin permissions)
      await page.context().clearCookies();
      await loginAs(page, "admin");

      // Create a connector and document set to enable the Knowledge toggle
      const onyxApiClient = new OnyxApiClient(page.request);
      ccPairId = await onyxApiClient.createFileConnector("Test Connector");
      documentSetId = await onyxApiClient.createDocumentSet(
        "Test Document Set",
        [ccPairId]
      );

      // Navigate to a page to ensure session is fully established
      await page.goto("/app");
      await page.waitForLoadState("networkidle");

      // Now login as a regular user to test the assistant creation
      await page.context().clearCookies();
      await loginAsRandomUser(page);

      // --- Initial Values ---
      const assistantName = `Test Assistant ${Date.now()}`;
      const assistantDescription = "This is a test assistant description.";
      const assistantInstructions = "These are the test instructions.";
      const assistantReminder = "Initial reminder.";
      const assistantStarterMessage = "Initial starter message?";

      // --- Edited Values ---
      const editedAssistantName = `Edited Assistant ${Date.now()}`;
      const editedAssistantDescription = "This is the edited description.";
      const editedAssistantInstructions = "These are the edited instructions.";
      const editedAssistantReminder = "Edited reminder.";
      const editedAssistantStarterMessage = "Edited starter message?";

      // Navigate to the assistant creation page
      await page.goto("/app/agents/create");

      // --- Fill in Initial Assistant Details ---
      await getNameInput(page).fill(assistantName);
      await getDescriptionInput(page).fill(assistantDescription);
      await getInstructionsTextarea(page).fill(assistantInstructions);

      // Reminder
      await getReminderTextarea(page).fill(assistantReminder);

      // Knowledge Cutoff Date
      await setKnowledgeCutoffDate(page);

      // Enable Knowledge toggle (should now be enabled due to connector)
      const knowledgeToggle = getKnowledgeToggle(page);
      await knowledgeToggle.scrollIntoViewIfNeeded();

      // Verify toggle is NOT disabled
      await expect(knowledgeToggle).not.toBeDisabled();
      await knowledgeToggle.click();

      // Navigate to document sets view and select the document set
      await navigateToDocumentSetsView(page);
      await selectDocumentSet(page, documentSetId);

      // Starter Message
      await getStarterMessageInput(page).fill(assistantStarterMessage);

      // Submit the creation form
      await getCreateSubmitButton(page).click();

      // Verify redirection to chat page with the new assistant ID
      await page.waitForURL(/.*\/app\?assistantId=\d+.*/);
      const url = page.url();
      const assistantIdMatch = url.match(/assistantId=(\d+)/);
      expect(assistantIdMatch).toBeTruthy();
      const assistantId = assistantIdMatch ? assistantIdMatch[1] : null;
      expect(assistantId).not.toBeNull();

      // Navigate directly to the edit page
      await page.goto(`/app/agents/edit/${assistantId}`);
      await page.waitForURL(`**/app/agents/edit/${assistantId}`);

      // Verify basic fields
      await expect(getNameInput(page)).toHaveValue(assistantName);
      await expect(getDescriptionInput(page)).toHaveValue(assistantDescription);
      await expect(getInstructionsTextarea(page)).toHaveValue(
        assistantInstructions
      );

      // Verify advanced fields
      await expect(getReminderTextarea(page)).toHaveValue(assistantReminder);
      // Knowledge toggle should be enabled since we have a connector
      await expect(getKnowledgeToggle(page)).toHaveAttribute(
        "aria-checked",
        "true"
      );
      // Verify document set is selected by navigating to the document sets view
      await navigateToDocumentSetsView(page);
      const documentSetRow = page.getByLabel(
        `document-set-row-${documentSetId}`
      );
      await expect(documentSetRow).toBeVisible();
      // The row should have a checked checkbox (data-selected attribute)
      await expect(documentSetRow).toHaveAttribute("data-selected", "true");

      await expect(getStarterMessageInput(page)).toHaveValue(
        assistantStarterMessage
      );

      // --- Edit Assistant Details ---
      await getNameInput(page).fill(editedAssistantName);
      await getDescriptionInput(page).fill(editedAssistantDescription);
      await getInstructionsTextarea(page).fill(editedAssistantInstructions);
      await getReminderTextarea(page).fill(editedAssistantReminder);
      await setKnowledgeCutoffDate(page);
      await getStarterMessageInput(page).fill(editedAssistantStarterMessage);

      // Submit the edit form
      await getUpdateSubmitButton(page).click();

      // Verify redirection back to the chat page
      await page.waitForURL(/.*\/app\?assistantId=\d+.*/);
      expect(page.url()).toContain(`assistantId=${assistantId}`);

      // --- Navigate to Edit Page Again and Verify Edited Values ---
      await page.goto(`/app/agents/edit/${assistantId}`);
      await page.waitForURL(`**/app/agents/edit/${assistantId}`);

      // Verify basic fields
      await expect(getNameInput(page)).toHaveValue(editedAssistantName);
      await expect(getDescriptionInput(page)).toHaveValue(
        editedAssistantDescription
      );
      await expect(getInstructionsTextarea(page)).toHaveValue(
        editedAssistantInstructions
      );

      // Verify advanced fields
      await expect(getReminderTextarea(page)).toHaveValue(
        editedAssistantReminder
      );
      await expect(getKnowledgeToggle(page)).toHaveAttribute(
        "aria-checked",
        "true"
      );
      // Verify document set is still selected after edit
      await navigateToDocumentSetsView(page);
      const documentSetRowAfterEdit = page.getByLabel(
        `document-set-row-${documentSetId}`
      );
      await expect(documentSetRowAfterEdit).toBeVisible();
      await expect(documentSetRowAfterEdit).toHaveAttribute(
        "data-selected",
        "true"
      );

      await expect(getStarterMessageInput(page)).toHaveValue(
        editedAssistantStarterMessage
      );

      console.log(
        `[test] Successfully tested Knowledge-enabled assistant: ${assistantName}`
      );
    });
  });
});
