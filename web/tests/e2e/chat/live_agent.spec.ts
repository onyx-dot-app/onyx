import { test } from "@playwright/test";
import { loginAsRandomUser } from "@tests/e2e/utils/auth";
import {
  sendMessage,
  startNewChat,
  verifyAgentIsChosen,
  verifyAgentIsChosenInSidebar,
  verifyDefaultAgentIsChosen,
} from "@tests/e2e/utils/chatActions";
import { createAgent } from "../utils/agentUtils";

test("Chat workflow", async ({ page }) => {
  // Clear cookies and log in as a random user
  await page.context().clearCookies();
  // Use waitForSelector for robustness instead of expect().toBeVisible()
  // await page.waitForSelector(
  //   `//div[@aria-label="Agents Modal"]//*[contains(text(), "${agentName}") and not(contains(@class, 'invisible'))]`,
  //   { state: "visible", timeout: 10000 }
  // );
  await loginAsRandomUser(page);

  // Navigate to the chat page
  await page.goto("/app");
  await page.waitForLoadState("networkidle");

  // Test interaction with the Default agent
  await sendMessage(page, "Hi");

  // Start a new chat session
  await startNewChat(page);

  // Verify the presence of the expected text
  await verifyDefaultAgentIsChosen(page);

  // Test creation of a new agent
  await page.getByTestId("AppSidebar/more-agents").click();
  await page.getByLabel("AgentsPage/new-agent-button").click();
  await page.locator('input[name="name"]').click();
  await page.locator('input[name="name"]').fill("Test Agent");
  await page.locator('textarea[name="description"]').click();
  await page
    .locator('textarea[name="description"]')
    .fill("Test Agent Description");
  await page.locator('textarea[name="instructions"]').click();
  await page
    .locator('textarea[name="instructions"]')
    .fill("Test Agent Instructions");
  await page.getByRole("button", { name: "Create" }).click();

  // Verify the successful creation of the new agent
  await verifyAgentIsChosen(page, "Test Agent");
  await verifyAgentIsChosenInSidebar(page, "Test Agent");

  // Send a message to create a chat session with this agent
  await sendMessage(page, "Hi");

  // Verify the agent is still selected in the sidebar

  // Hard refresh the page
  await page.reload({ waitUntil: "networkidle" });

  // The custom agent should still be selected
  await verifyAgentIsChosenInSidebar(page, "Test Agent");

  // Start another new chat session
  await startNewChat(page);
  await page.waitForLoadState("networkidle");

  // Verify the presence of the default agent text
  await verifyDefaultAgentIsChosen(page);
});
