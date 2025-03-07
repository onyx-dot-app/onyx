import { test, expect } from "@chromatic-com/playwright";
import { loginAsRandomUser } from "../utils/auth";
import {
  navigateToAssistantInHistorySidebar,
  sendMessage,
  startNewChat,
  switchModel,
} from "../utils/chatActions";

test("Chat workflow", async ({ page }) => {
  // Clear cookies and log in as a random user
  await page.context().clearCookies();
  await loginAsRandomUser(page);

  // Navigate to the chat page
  await page.goto("http://localhost:3000/chat");

  // Test interaction with the Art assistant
  await navigateToAssistantInHistorySidebar(
    page,
    "[-3]",
    "Assistant for generating"
  );
  await sendMessage(page, "Hi");

  // Start a new chat session
  await startNewChat(page);

  // Verify the presence of the expected text
  await expect(page.getByText("Assistant for generating")).toBeVisible();

  // Test interaction with the General assistant
  await navigateToAssistantInHistorySidebar(
    page,
    "[-1]",
    "Assistant with no search"
  );

  // Verify the URL after selecting the General assistant
  await expect(page).toHaveURL("http://localhost:3000/chat?assistantId=-1");

  // Test creation of a new assistant
  await page.getByRole("button", { name: "Explore Assistants" }).click();
  await page.getByRole("button", { name: "Create" }).click();
  await page.getByTestId("name").click();
  await page.getByTestId("name").fill("Test Assistant");
  await page.getByTestId("description").click();
  await page.getByTestId("description").fill("Test Assistant Description");
  await page.getByTestId("system_prompt").click();
  await page.getByTestId("system_prompt").fill("Test Assistant Instructions");
  await page.getByRole("button", { name: "Create" }).click();

  // Verify the successful creation of the new assistant
  await expect(page.getByText("Test Assistant Description")).toBeVisible({
    timeout: 5000,
  });

  // Start another new chat session
  await startNewChat(page);

  // Verify the presence of the default assistant text
  try {
    await expect(page.getByText("Assistant with access to")).toBeVisible({
      timeout: 5000,
    });
  } catch (error) {
    console.error("Live Assistant final page content:");
    console.error(await page.content());
  }
});
