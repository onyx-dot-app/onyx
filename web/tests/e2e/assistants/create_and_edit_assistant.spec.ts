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

// Helper function to set date using InputDatePicker
const setKnowledgeCutoffDate = async (page: Page, dateString: string) => {
  // Parse date string explicitly as YYYY-MM-DD to avoid timezone issues
  const [yearStr, monthStr, dayStr] = dateString.split("-");
  const year = parseInt(yearStr);
  const month = parseInt(monthStr) - 1; // 0-based (January = 0)
  const day = parseInt(dayStr);

  // Find and click the date picker button within the Knowledge Cutoff Date section
  const datePickerButton = page
    .locator('label:has-text("Knowledge Cutoff Date")')
    .locator("..")
    .locator('button:has-text("Select Date"), button:has-text("/")');

  await datePickerButton.first().click();

  // Wait for the popover to open
  await page.waitForSelector('[role="dialog"]', {
    state: "visible",
    timeout: 5000,
  });

  // Select the year from dropdown
  const yearSelect = page
    .locator('[role="dialog"]')
    .locator('button[role="combobox"]');
  await yearSelect.click();
  await page.getByRole("option", { name: `${year}` }).click();

  // Wait for year selection to take effect
  await page.waitForTimeout(500);

  // After selecting the year, the calendar defaults to January of that year
  // We need to navigate to the correct month
  const monthNames = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
  ];
  const targetMonthName = monthNames[month];

  // Keep clicking next/previous month until we reach the target month
  let attempts = 0;
  const maxAttempts = 12;

  while (attempts < maxAttempts) {
    // Check current month displayed in calendar
    const currentMonthElement = page
      .locator('[role="dialog"]')
      .locator(
        "text=/January|February|March|April|May|June|July|August|September|October|November|December/"
      )
      .first();
    const currentMonthText = await currentMonthElement.textContent();

    if (currentMonthText?.includes(targetMonthName)) {
      break; // We're at the right month
    }

    // Determine if we need to go forward or backward
    const currentMonthIndex = monthNames.findIndex(
      (m) => currentMonthText?.includes(m)
    );

    if (currentMonthIndex < month) {
      // Click next month button
      await page
        .locator('[role="dialog"]')
        .locator('button[aria-label*="Next"]')
        .click();
    } else {
      // Click previous month button
      await page
        .locator('[role="dialog"]')
        .locator('button[aria-label*="Previous"]')
        .click();
    }

    await page.waitForTimeout(200);
    attempts++;
  }

  // Now click the day in the calendar
  // First, ensure we're on the right month/year before clicking
  await page.waitForTimeout(300);

  const dayButton = page
    .locator('[role="dialog"]')
    .locator('button[role="gridcell"]')
    .filter({ hasText: new RegExp(`^${day}$`) })
    .and(page.locator(":not([disabled])"))
    .first();

  // Wait for the day button to be visible and enabled
  await dayButton.waitFor({ state: "visible", timeout: 5000 });
  await dayButton.click();

  // The popover should close automatically after selection
  await page.waitForSelector('[role="dialog"]', {
    state: "hidden",
    timeout: 5000,
  });
};

// Helper function to verify the displayed date in the date picker
const verifyKnowledgeCutoffDate = async (page: Page, dateString: string) => {
  // Parse date string explicitly as YYYY-MM-DD and create a date object
  const [yearStr, monthStr, dayStr] = dateString.split("-");
  const date = new Date(
    parseInt(yearStr),
    parseInt(monthStr) - 1,
    parseInt(dayStr)
  );
  const formattedDate = date.toLocaleDateString();

  const datePickerButton = page
    .locator('label:has-text("Knowledge Cutoff Date")')
    .locator("..")
    .locator(`button:has-text("${formattedDate}")`);

  await expect(datePickerButton.first()).toBeVisible();
};
const getStarterMessageInput = (page: Page, index: number = 0) =>
  page.locator(`input[name="starter_messages.${index}"]`);
const getCreateSubmitButton = (page: Page) =>
  page.locator('button[type="submit"]:has-text("Create")');
const getUpdateSubmitButton = (page: Page) =>
  page.locator('button[type="submit"]:has-text("Update")');
const getKnowledgeSourceSelect = (page: Page) =>
  page
    .locator('label:has-text("Knowledge Source")')
    .locator('button[role="combobox"]')
    .first();

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

      // Enable Knowledge toggle
      const knowledgeToggle = getKnowledgeToggle(page);
      await knowledgeToggle.scrollIntoViewIfNeeded();
      await expect(knowledgeToggle).toHaveAttribute("aria-checked", "false");
      await knowledgeToggle.click();

      // Select "User Knowledge" from the knowledge source dropdown
      const knowledgeSourceSelect = getKnowledgeSourceSelect(page);
      await knowledgeSourceSelect.click();
      await page.getByRole("option", { name: "User Knowledge" }).click();

      // Verify "Add User Files" button is visible
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

      // --- Edited Values ---
      const editedAssistantName = `Edited Assistant ${Date.now()}`;
      const editedAssistantDescription = "This is the edited description.";
      const editedAssistantInstructions = "These are the edited instructions.";
      const editedAssistantReminder = "Edited reminder.";
      const editedAssistantStarterMessage = "Edited starter message?";
      const editedKnowledgeCutoffDate = "2024-01-01";

      // Navigate to the assistant creation page
      await page.goto("http://localhost:3000/chat/agents/create");

      // --- Fill in Initial Assistant Details ---
      await getNameInput(page).fill(assistantName);
      await getDescriptionInput(page).fill(assistantDescription);
      await getInstructionsTextarea(page).fill(assistantInstructions);

      // Reminder
      await getReminderTextarea(page).fill(assistantReminder);

      // Knowledge Cutoff Date
      await setKnowledgeCutoffDate(page, knowledgeCutoffDate);

      // Enable Knowledge toggle (should now be enabled due to connector)
      const knowledgeToggle = getKnowledgeToggle(page);
      await knowledgeToggle.scrollIntoViewIfNeeded();

      // Verify toggle is NOT disabled
      await expect(knowledgeToggle).not.toBeDisabled();
      await knowledgeToggle.click();

      // Select "Team Knowledge" from the knowledge source dropdown
      const knowledgeSourceSelect = getKnowledgeSourceSelect(page);
      await knowledgeSourceSelect.click();
      await page.getByRole("option", { name: "Team Knowledge" }).click();

      // Select the document set created in beforeAll
      // Document sets are rendered as clickable cards, not a dropdown
      await page.getByTestId(`document-set-card-${documentSetId}`).click();

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

      // Verify advanced fields
      await expect(getReminderTextarea(page)).toHaveValue(assistantReminder);
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
      await verifyKnowledgeCutoffDate(page, knowledgeCutoffDate);
      await expect(getStarterMessageInput(page)).toHaveValue(
        assistantStarterMessage
      );

      // --- Edit Assistant Details ---
      await getNameInput(page).fill(editedAssistantName);
      await getDescriptionInput(page).fill(editedAssistantDescription);
      await getInstructionsTextarea(page).fill(editedAssistantInstructions);
      await getReminderTextarea(page).fill(editedAssistantReminder);
      await setKnowledgeCutoffDate(page, editedKnowledgeCutoffDate);
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

      // Verify advanced fields
      await expect(getReminderTextarea(page)).toHaveValue(
        editedAssistantReminder
      );
      await expect(getKnowledgeToggle(page)).toHaveAttribute(
        "aria-checked",
        "true"
      );
      // Verify document set is still selected after edit
      await expect(
        page.getByTestId(`document-set-card-${documentSetId}`)
      ).toBeVisible();
      await verifyKnowledgeCutoffDate(page, editedKnowledgeCutoffDate);
      await expect(getStarterMessageInput(page)).toHaveValue(
        editedAssistantStarterMessage
      );

      console.log(
        `[test] Successfully tested Knowledge-enabled assistant: ${assistantName}`
      );
    });
  });
});
