import { test } from "@playwright/test";
import { loginAsRandomUser } from "@tests/e2e/utils/auth";
import {
  grantAddAgents,
  deleteGrantGroups,
} from "@tests/e2e/utils/grantPermissions";
import {
  sendMessage,
  startNewChat,
  verifyAgentIsChosen,
  verifyDefaultAgentIsChosen,
} from "@tests/e2e/utils/chatActions";

test.describe("Live Agent Tests", () => {
  const grantGroupIds: number[] = [];

  test.afterAll(async ({ browser }) => {
    await deleteGrantGroups(browser, grantGroupIds);
    grantGroupIds.length = 0;
  });

  test("Chat workflow", async ({ page, browser }) => {
    // Clear cookies and log in as a random user
    await page.context().clearCookies();
    const { email } = await loginAsRandomUser(page);
    // this flow creates an agent through the UI, which EE gates
    grantGroupIds.push(await grantAddAgents(browser, email));

    // Navigate to the chat page
    await page.goto("/app");
    await page.waitForLoadState("networkidle");

    // Test interaction with the Default agent
    await sendMessage(page, "Hi");

    // Start a new chat session
    await startNewChat(page);

    // Verify the presence of the expected text
    await verifyDefaultAgentIsChosen(page);

    // Test creation of a new assistant
    await page.getByTestId("AppSidebar/more-agents").click();
    await page.getByLabel("AgentsPage/new-agent-button").click();
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
    await verifyAgentIsChosen(page, "Test Assistant");

    // Start another new chat session
    await startNewChat(page);
    await page.waitForLoadState("networkidle");

    // Verify the presence of the default agent text
    await verifyDefaultAgentIsChosen(page);
  });
});
