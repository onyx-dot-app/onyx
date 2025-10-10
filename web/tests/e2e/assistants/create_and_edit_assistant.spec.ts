import { test, expect } from "@chromatic-com/playwright";
import { Page } from "@playwright/test";
import { loginAsRandomUser } from "../utils/auth";

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
  page.getByRole("checkbox", { name: /Date and Time Aware/i });
const getKnowledgeCutoffInput = (page: Page) =>
  page.locator('input[name="search_start_date"]');
const getKnowledgeToggle = (page: Page) =>
  page
    .locator('div:has(> p:has-text("Knowledge"))')
    .locator('button[role="switch"]');
const getNumChunksInput = (page: Page) =>
  page.locator('input[name="num_chunks"]');
const getAiRelevanceCheckbox = (page: Page) =>
  page.getByRole("checkbox", { name: /AI Relevance Filter/i });
const getStarterMessageInput = (page: Page, index: number = 0) =>
  page.locator(`input[name="starter_messages.${index}.message"]`);
const getCreateSubmitButton = (page: Page) =>
  page.locator('button[type="submit"]:has-text("Create")');
const getUpdateSubmitButton = (page: Page) =>
  page.locator('button[type="submit"]:has-text("Update")');

test("Assistant Creation and Edit Verification", async ({ page }) => {
  await page.context().clearCookies();
  await loginAsRandomUser(page);

  // --- Initial Values ---
  const assistantName = `Test Assistant ${Date.now()}`;
  const assistantDescription = "This is a test assistant description.";
  const assistantInstructions = "These are the test instructions.";
  const assistantReminder = "Initial reminder.";
  const assistantStarterMessage = "Initial starter message?";
  const knowledgeCutoffDate = "2023-01-01"; // YYYY-MM-DD format
  const numChunks = "5";

  // --- Edited Values ---
  const editedAssistantName = `Edited Assistant ${Date.now()}`;
  const editedAssistantDescription = "This is the edited description.";
  const editedAssistantInstructions = "These are the edited instructions.";
  const editedAssistantReminder = "Edited reminder.";
  const editedAssistantStarterMessage = "Edited starter message?";
  const editedKnowledgeCutoffDate = "2024-01-01"; // YYYY-MM-DD format
  const editedNumChunks = "15";

  // Navigate to the assistant creation page
  await page.goto("http://localhost:3000/assistants/new");

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

  // Num Chunks
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

  // --- Navigate to Edit Page and Verify Initial Values ---
  // Navigate through the Assistant Explorer modal
  await page.getByTestId("AppSidebar/more-agents").click();

  // Find the assistant card in the modal and scroll to it
  const modalContent = page.getByTestId("AgentsModal/container");
  const modalBox = await modalContent.boundingBox();
  if (modalBox) {
    await page.mouse.move(
      modalBox.x + modalBox.width / 2,
      modalBox.y + modalBox.height / 2
    );
    // Increase scroll distance if needed
    await page.mouse.wheel(0, 1000);
    await page.waitForTimeout(500); // Add a small wait after scroll
  }

  await page.getByTestId("AgentCard/more").first().click();

  // Wait for the popover to appear and click the "Edit" button
  const editButton = page.getByTestId("AgentCard/edit").first();
  await editButton.click();

  // Verify we are on the edit page
  await page.waitForURL(`**/assistants/edit/${assistantId}`);

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
  await expect(getKnowledgeToggle(page)).toHaveAttribute(
    "aria-checked",
    "false"
  );
  await expect(getKnowledgeCutoffInput(page)).toHaveValue(knowledgeCutoffDate);
  // This should still be 0.
  //
  // Since "seeded docs" are disabled, "search" (the "Knowledge" toggle) will be disabled.
  // Since "search" is disabled, modifying the "num_chunks" will NOT work (the frontend will override the value sent to the backend to be 0).
  // ```ts
  // // (AssistantEditor.tsx):
  // const numChunks = searchToolEnabled ? values.num_chunks || 25 : 0;
  // ```
  await expect(getNumChunksInput(page)).toHaveValue("0");
  await expect(getAiRelevanceCheckbox(page)).toHaveAttribute(
    "aria-checked",
    "true"
  );
  await expect(getStarterMessageInput(page)).toHaveValue(
    assistantStarterMessage
  );

  // --- Edit Assistant Details ---
  // Basic Fields
  await getNameInput(page).fill(editedAssistantName);
  await getDescriptionInput(page).fill(editedAssistantDescription);
  await getInstructionsTextarea(page).fill(editedAssistantInstructions);

  // Advanced Fields
  await getReminderTextarea(page).fill(editedAssistantReminder);
  // Date/Time Aware (Disable) - Click to toggle from true to false
  await getDateTimeAwareCheckbox(page).click();
  await getKnowledgeCutoffInput(page).fill(editedKnowledgeCutoffDate);
  await getNumChunksInput(page).fill(editedNumChunks);
  // AI Relevance Filter (Disable) - Click to toggle from true to false
  await getAiRelevanceCheckbox(page).click();
  await getStarterMessageInput(page).fill(editedAssistantStarterMessage);

  // Submit the edit form
  await getUpdateSubmitButton(page).click();

  // Verify redirection back to the chat page
  await page.waitForURL(/.*\/chat\?assistantId=\d+.*/);
  expect(page.url()).toContain(`assistantId=${assistantId}`);

  // --- Navigate to Edit Page Again and Verify Edited Values ---
  // Use direct navigation this time
  await page.goto(`http://localhost:3000/assistants/edit/${assistantId}`);
  await page.waitForURL(`**/assistants/edit/${assistantId}`);

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
  await expect(getReminderTextarea(page)).toHaveValue(editedAssistantReminder);
  await expect(getDateTimeAwareCheckbox(page)).toHaveAttribute(
    "aria-checked",
    "false"
  ); // Now disabled
  await expect(getKnowledgeToggle(page)).toHaveAttribute(
    "aria-checked",
    "false"
  );
  await expect(getKnowledgeCutoffInput(page)).toHaveValue(
    editedKnowledgeCutoffDate
  );

  // Once again, this will still not work.
  await expect(getNumChunksInput(page)).toHaveValue("0");
  await expect(getAiRelevanceCheckbox(page)).toHaveAttribute(
    "aria-checked",
    "false"
  ); // Now disabled
  await expect(getStarterMessageInput(page)).toHaveValue(
    editedAssistantStarterMessage
  );
});
