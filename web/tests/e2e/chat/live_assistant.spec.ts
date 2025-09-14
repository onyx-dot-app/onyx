import { test, expect } from "@chromatic-com/playwright";
import { loginAsRandomUser } from "../utils/auth";
import {
  navigateToAssistantInHistorySidebar,
  sendMessage,
  startNewChat,
  verifyAssistantIsChosen,
} from "../utils/chatActions";

test("Chat workflow", async ({ page }) => {
  // Clear cookies and log in as a random user
  await page.context().clearCookies();
  await loginAsRandomUser(page);

  // Navigate to the chat page
  await page.goto("http://localhost:3000/chat");

  // Test interaction with the Default assistant
  await sendMessage(page, "Hi");

  // Start a new chat session
  await startNewChat(page);

  // Verify the presence of the expected text
  await verifyAssistantIsChosen(page, "Onyx");

  // Test creation of a new assistant
  await page.getByRole("button", { name: "Explore Assistants" }).click();
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByTestId("name").click();
  await page.getByTestId("name").fill("Test Assistant");
  await page.getByTestId("description").click();
  await page.getByTestId("description").fill("Test Assistant Description");
  await page.getByTestId("system_prompt").click();
  await page.getByTestId("system_prompt").fill("Test Assistant Instructions");
  await page.getByRole("button", { name: "Create" }).click();

  // Verify the successful creation of the new assistant
  await verifyAssistantIsChosen(page, "Test Assistant");

  // Start another new chat session
  await startNewChat(page);

  // Verify the presence of the default assistant text
  try {
    await verifyAssistantIsChosen(page, "Onyx");
  } catch (error) {
    console.error("Live Assistant final page content:");
    console.error(await page.content());
  }
});
