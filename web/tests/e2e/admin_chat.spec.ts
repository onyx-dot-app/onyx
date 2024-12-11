import { test, expect } from "@playwright/test";
test(
  `test - admin chat`,
  {
    tag: "@admin",
  },
  async ({ page }) => {
    await page.goto("http://localhost:3000/assistants/new");
    await expect(page).toHaveURL("http://localhost:3000/assistants/new");
    await page.screenshot({
      path: `screenshots/create_assistant_page.png`,
    });
    await page.getByTestId("name").click();
    await page.getByTestId("name").fill("Test");
    await page.getByTestId("description").click();
    await page.getByTestId("description").fill("Test");
    await page.getByTestId("system_prompt").click();
    await page.getByTestId("system_prompt").fill("Test");
    await page
      .getByRole("button", { name: "Logo GPT 4o", exact: true })
      .click();
    await page.getByRole("button", { name: "Create!" }).click();
    // Wait for the page URL to change to the chat page
    await page.waitForURL(/^http:\/\/localhost:3000\/chat(\?.*)?$/);
    await expect(page.url()).toContain("http://localhost:3000/chat");
    await page.screenshot({
      path: `screenshots/chat_page_after_create.png`,
    });
    await page.getByPlaceholder("Send a message or try using").fill("Hello");
    await page.keyboard.press("Enter");
    await page.waitForSelector("#danswer-ai-message", { state: "visible" });
  }
);
