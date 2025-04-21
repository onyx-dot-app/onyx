import { test, expect } from "@chromatic-com/playwright";
import { dragElementAbove, dragElementBelow } from "../utils/dragUtils";
import { loginAsRandomUser } from "../utils/auth";

test("Assistant Drag and Drop", async ({ page }) => {
  await page.context().clearCookies();
  await loginAsRandomUser(page);

  // Navigate to the chat page
  await page.goto("http://localhost:3000/chat");

  // Helper function to get the current order of assistants
  const getAssistantOrder = async () => {
    const assistants = await page.$$('[data-testid^="assistant-["]');
    return Promise.all(
      assistants.map(async (assistant) => {
        const nameElement = await assistant.$("p");
        return nameElement ? nameElement.textContent() : "";
      })
    );
  };

  // Get the initial order
  const initialOrder = await getAssistantOrder();

  // Drag second assistant above first
  const secondAssistant = page.locator('[data-testid^="assistant-["]').nth(1);
  const firstAssistant = page.locator('[data-testid^="assistant-["]').nth(0);

  await dragElementAbove(secondAssistant, firstAssistant, page);

  // Check new order
  const orderAfterDragUp = await getAssistantOrder();
  expect(orderAfterDragUp[0]).toBe(initialOrder[1]);
  expect(orderAfterDragUp[1]).toBe(initialOrder[0]);

  // Drag last assistant to second position
  const assistants = page.locator('[data-testid^="assistant-["]');
  const lastIndex = (await assistants.count()) - 1;
  const lastAssistant = assistants.nth(lastIndex);
  const secondPosition = assistants.nth(1);

  await page.waitForTimeout(3000);
  await dragElementBelow(lastAssistant, secondPosition, page);

  // Check new order
  const orderAfterDragDown = await getAssistantOrder();
  expect(orderAfterDragDown[1]).toBe(initialOrder[lastIndex]);

  // Refresh and verify order
  await page.reload();
  const orderAfterRefresh = await getAssistantOrder();
  expect(orderAfterRefresh).toEqual(orderAfterDragDown);
});
