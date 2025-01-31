import { test, expect } from "@playwright/test";

// Use pre-signed in "admin" storage state
test.use({
  storageState: "admin_auth.json",
});

test("Chat workflow", async ({ page }) => {
  // Initial setup
  await page.goto("http://localhost:3000/chat", { timeout: 3000 });

  // Interact with Art assistant
  await page.locator("button").filter({ hasText: "Art" }).click();
  await page.getByPlaceholder("Message Art assistant...").fill("Hi");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(3000);

  // Start a new chat
  await page.getByRole("link", { name: "Start New Chat" }).click();
  await page.waitForNavigation({ waitUntil: "networkidle" });

  // Check for expected text
  await expect(page.getByText("Assistant for generating")).toBeVisible();

  // Interact with General assistant
  await page.locator("button").filter({ hasText: "General" }).click();

  // Check URL after clicking General assistant
  await expect(page).toHaveURL("http://localhost:3000/chat?assistantId=-1", {
    timeout: 5000,
  });

  // Create a new assistant
  await page.getByRole("button", { name: "Explore Assistants" }).click();
  await page.getByRole("button", { name: "Create" }).click();
  await page.getByTestId("name").click();
  await page.getByTestId("name").fill("Test Assistant");
  await page.getByTestId("description").click();
  await page.getByTestId("description").fill("Test Assistant Description");
  await page.getByTestId("system_prompt").click();
  await page.getByTestId("system_prompt").fill("Test Assistant Instructions");
  await page.getByRole("button", { name: "Create" }).click();

  // Verify new assistant creation
  await expect(page.getByText("Test Assistant Description")).toBeVisible({
    timeout: 5000,
  });

  // Start another new chat
  await page.getByRole("link", { name: "Start New Chat" }).click();
  await expect(page.getByText("Assistant with access to")).toBeVisible({
    timeout: 5000,
  });
});
