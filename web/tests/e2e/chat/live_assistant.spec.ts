import { test } from "@chromatic-com/playwright";
import { loginAsRandomUser } from "../utils/auth";
import {
  sendMessage,
  startNewChat,
  verifyAssistantIsChosen,
  verifyDefaultAssistantIsChosen,
} from "../utils/chatActions";

test("Chat workflow", async ({ page }) => {
  // Clear cookies and log in as a random user
  await page.context().clearCookies();
  // Use waitForSelector for robustness instead of expect().toBeVisible()
  // await page.waitForSelector(
  //   `//div[@aria-label="Agents Modal"]//*[contains(text(), "${assistantName}") and not(contains(@class, 'invisible'))]`,
  //   { state: "visible", timeout: 10000 }
  // );
  await loginAsRandomUser(page);

  // Navigate to the chat page
  await page.goto("/chat");
  await page.waitForLoadState("networkidle");

  // Test interaction with the Default assistant
  await sendMessage(page, "Hi");

  // Start a new chat session
  await startNewChat(page);

  // Verify the presence of the expected text
  await verifyDefaultAssistantIsChosen(page);

  // Test creation of a new assistant
  await page.getByTestId("AppSidebar/more-agents").click();
  await page.getByTestId("AgentsPage/new-agent-button").click();
  await page.locator('input[name="name"]').click();
  await page.locator('input[name="name"]').fill("Test Assistant");
  await page.locator('textarea[name="description"]').click();
  await page
    .locator('textarea[name="description"]')
    .fill("Test Assistant Description");
  await page.locator('textarea[name="instructions"]').click();
  await page
    .locator('textarea[name="instructions"]')
    .fill("Test Assistant Instructions");
  await page.getByRole("button", { name: "Create" }).click();

  // Verify the successful creation of the new assistant
  await verifyAssistantIsChosen(page, "Test Assistant");

  // Start another new chat session
  await startNewChat(page);
  await page.waitForLoadState("networkidle");

  // Verify the presence of the default assistant text
  await verifyDefaultAssistantIsChosen(page);
});
