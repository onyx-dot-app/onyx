import { test, expect, Page, Browser } from "@playwright/test";
import { loginAs, loginAsRandomUser } from "../utils/auth";
import { OnyxApiClient } from "../utils/onyxApiClient";

// --- Locator Helper Functions ---
const getNameInput = (page: Page) => page.locator('input[name="name"]');
const getDescriptionInput = (page: Page) =>
  page.locator('input[name="description"]');
const getInstructionsTextarea = (page: Page) =>
  page.locator('textarea[name="system_prompt"]');
const getAdvancedOptionsButton = (page: Page) =>
  page.locator('button:has-text("Advanced Options")');
const getReminderTextarea = (page: Page) =>
  page.locator('textarea[name="task_prompt"]');
const getDateTimeAwareCheckbox = (page: Page) =>
  page.locator("#checkbox-datetime_aware");
const getKnowledgeCutoffInput = (page: Page) =>
  page.locator('input[name="search_start_date"]');
const getAiRelevanceCheckbox = (page: Page) =>
  page.locator("#checkbox-llm_relevance_filter");
const getKnowledgeToggle = (page: Page) =>
  page
    .locator('div:has(> p:has-text("Knowledge"))')
    .locator('button[role="switch"]');
const getNumChunksInput = (page: Page) =>
  page.locator('input[name="num_chunks"]');
const getStarterMessageInput = (page: Page, index: number = 0) =>
  page.locator(`input[name="starter_messages.${index}.message"]`);
const getCreateSubmitButton = (page: Page) =>
  page.locator('button[type="submit"]:has-text("Create")');
const getUpdateSubmitButton = (page: Page) =>
  page.locator('button[type="submit"]:has-text("Update")');

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

      await page.goto("http://localhost:3000/chat/agents/create");

      // Fill in basic assistant details
      await getNameInput(page).fill(assistantName);
      await getDescriptionInput(page).fill(assistantDescription);
      await getInstructionsTextarea(page).fill(assistantInstructions);

      // Verify Knowledge toggle is disabled (no connectors)
      const knowledgeToggle = getKnowledgeToggle(page);
      await knowledgeToggle.scrollIntoViewIfNeeded();
      await expect(knowledgeToggle).toHaveAttribute("aria-checked", "false");

      // Verify "Add User Files" button is visible even without connectors
      const addUserFilesButton = page.getByRole("button", {
        name: /add user files/i,
      });
      await expect(addUserFilesButton).toBeVisible();

      // Submit the assistant creation form
      await getCreateSubmitButton(page).click();

      // Verify redirection to chat page with the new assistant
      await page.waitForURL(/.*\/chat\?assistantId=\d+.*/);
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
        const cleanupClient = new OnyxApiClient(page);
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
      const onyxApiClient = new OnyxApiClient(page);
      ccPairId = await onyxApiClient.createFileConnector("Test Connector");
      documentSetId = await onyxApiClient.createDocumentSet(
        "Test Document Set",
        [ccPairId]
      );

      // Navigate to a page to ensure session is fully established
      await page.goto("http://localhost:3000/chat");
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
      const knowledgeCutoffDate = "2023-01-01";
      const numChunks = "5";

      // --- Edited Values ---
      const editedAssistantName = `Edited Assistant ${Date.now()}`;
      const editedAssistantDescription = "This is the edited description.";
      const editedAssistantInstructions = "These are the edited instructions.";
      const editedAssistantReminder = "Edited reminder.";
      const editedAssistantStarterMessage = "Edited starter message?";
      const editedKnowledgeCutoffDate = "2024-01-01";
      const editedNumChunks = "15";

      // Navigate to the assistant creation page
      await page.goto("http://localhost:3000/chat/agents/create");

      // --- Fill in Initial Assistant Details ---
      await getNameInput(page).fill(assistantName);
      await getDescriptionInput(page).fill(assistantDescription);
      await getInstructionsTextarea(page).fill(assistantInstructions);

      // --- Open Advanced Options ---
      const advancedOptionsButton = getAdvancedOptionsButton(page);
      await advancedOptionsButton.scrollIntoViewIfNeeded();
      await advancedOptionsButton.click();

      // --- Fill Advanced Fields ---

      // Reminder
      await getReminderTextarea(page).fill(assistantReminder);

      // Date/Time Aware (Enable)
      await getDateTimeAwareCheckbox(page).click();

      // Knowledge Cutoff Date
      await getKnowledgeCutoffInput(page).fill(knowledgeCutoffDate);

      // Enable Knowledge toggle (should now be enabled due to connector)
      const knowledgeToggle = getKnowledgeToggle(page);
      await knowledgeToggle.scrollIntoViewIfNeeded();

      // Verify toggle is NOT disabled
      await expect(knowledgeToggle).not.toBeDisabled();
      await knowledgeToggle.click();

      // Select the document set created in beforeAll
      // Document sets are rendered as clickable cards, not a dropdown
      await page.getByTestId(`document-set-card-${documentSetId}`).click();

      // Num Chunks (should work now that Knowledge is enabled)
      await getNumChunksInput(page).fill(numChunks);

      // AI Relevance Filter (Enable)
      await getAiRelevanceCheckbox(page).click();

      // Starter Message
      await getStarterMessageInput(page).fill(assistantStarterMessage);

      // Submit the creation form
      await getCreateSubmitButton(page).click();

      // Verify redirection to chat page with the new assistant ID
      await page.waitForURL(/.*\/chat\?assistantId=\d+.*/);
      const url = page.url();
      const assistantIdMatch = url.match(/assistantId=(\d+)/);
      expect(assistantIdMatch).toBeTruthy();
      const assistantId = assistantIdMatch ? assistantIdMatch[1] : null;
      expect(assistantId).not.toBeNull();

      // Navigate directly to the edit page
      await page.goto(`http://localhost:3000/chat/agents/edit/${assistantId}`);
      await page.waitForURL(`**/chat/agents/edit/${assistantId}`);

      // Verify basic fields
      await expect(getNameInput(page)).toHaveValue(assistantName);
      await expect(getDescriptionInput(page)).toHaveValue(assistantDescription);
      await expect(getInstructionsTextarea(page)).toHaveValue(
        assistantInstructions
      );

      // Open Advanced Options
      const advancedOptionsButton1 = getAdvancedOptionsButton(page);
      await advancedOptionsButton1.scrollIntoViewIfNeeded();
      await advancedOptionsButton1.click();

      // Verify advanced fields
      await expect(getReminderTextarea(page)).toHaveValue(assistantReminder);
      await expect(getDateTimeAwareCheckbox(page)).toHaveAttribute(
        "aria-checked",
        "true"
      );
      // Knowledge toggle should be enabled since we have a connector
      await expect(getKnowledgeToggle(page)).toHaveAttribute(
        "aria-checked",
        "true"
      );
      // Verify document set is selected (cards show selected state with different background)
      // The selected document set card should be visible
      await expect(
        page.getByTestId(`document-set-card-${documentSetId}`)
      ).toBeVisible();
      await expect(getKnowledgeCutoffInput(page)).toHaveValue(
        knowledgeCutoffDate
      );
      await expect(getNumChunksInput(page)).toHaveValue(numChunks);
      await expect(getAiRelevanceCheckbox(page)).toHaveAttribute(
        "aria-checked",
        "true"
      );
      await expect(getStarterMessageInput(page)).toHaveValue(
        assistantStarterMessage
      );

      // --- Edit Assistant Details ---
      await getNameInput(page).fill(editedAssistantName);
      await getDescriptionInput(page).fill(editedAssistantDescription);
      await getInstructionsTextarea(page).fill(editedAssistantInstructions);
      await getReminderTextarea(page).fill(editedAssistantReminder);
      await getDateTimeAwareCheckbox(page).click(); // Disable
      await getKnowledgeCutoffInput(page).fill(editedKnowledgeCutoffDate);
      await getNumChunksInput(page).fill(editedNumChunks);
      await getAiRelevanceCheckbox(page).click(); // Disable
      await getStarterMessageInput(page).fill(editedAssistantStarterMessage);

      // Submit the edit form
      await getUpdateSubmitButton(page).click();

      // Verify redirection back to the chat page
      await page.waitForURL(/.*\/chat\?assistantId=\d+.*/);
      expect(page.url()).toContain(`assistantId=${assistantId}`);

      // --- Navigate to Edit Page Again and Verify Edited Values ---
      await page.goto(`http://localhost:3000/chat/agents/edit/${assistantId}`);
      await page.waitForURL(`**/chat/agents/edit/${assistantId}`);

      // Verify basic fields
      await expect(getNameInput(page)).toHaveValue(editedAssistantName);
      await expect(getDescriptionInput(page)).toHaveValue(
        editedAssistantDescription
      );
      await expect(getInstructionsTextarea(page)).toHaveValue(
        editedAssistantInstructions
      );

      // Open Advanced Options
      const advancedOptionsButton2 = getAdvancedOptionsButton(page);
      await advancedOptionsButton2.scrollIntoViewIfNeeded();
      await advancedOptionsButton2.click();

      // Verify advanced fields
      await expect(getReminderTextarea(page)).toHaveValue(
        editedAssistantReminder
      );
      await expect(getDateTimeAwareCheckbox(page)).toHaveAttribute(
        "aria-checked",
        "false"
      );
      await expect(getKnowledgeToggle(page)).toHaveAttribute(
        "aria-checked",
        "true"
      );
      // Verify document set is still selected after edit
      await expect(
        page.getByTestId(`document-set-card-${documentSetId}`)
      ).toBeVisible();
      await expect(getKnowledgeCutoffInput(page)).toHaveValue(
        editedKnowledgeCutoffDate
      );
      await expect(getNumChunksInput(page)).toHaveValue(editedNumChunks);
      await expect(getAiRelevanceCheckbox(page)).toHaveAttribute(
        "aria-checked",
        "false"
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
