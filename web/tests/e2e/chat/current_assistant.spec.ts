import { test, expect } from "@chromatic-com/playwright";
import { dragElementAbove, dragElementBelow } from "../utils/dragUtils";
import { loginAsRandomUser } from "../utils/auth";
import { createAssistant, pinAssistantByName } from "../utils/assistantUtils";

// TODO (chris): figure out why this test is flakey
test.skip("Assistant Drag and Drop", async ({ page }) => {
  await page.context().clearCookies();
  await loginAsRandomUser(page);

  // Navigate to the chat page
  await page.goto("http://localhost:3000/chat");

  // Ensure at least two assistants exist for drag-and-drop
  const ts = Date.now();
  const nameA = `E2E Assistant A ${ts}`;
  const nameB = `E2E Assistant B ${ts}`;
  const nameC = `E2E Assistant C ${ts}`;
  await createAssistant(page, {
    name: nameA,
    description: "E2E-created assistant A",
    instructions: "Assistant A instructions",
  });
  await pinAssistantByName(page, nameA);
  await expect(
    page.locator('[data-testid^="assistant-["]').filter({ hasText: nameA })
  ).toBeVisible();

  await createAssistant(page, {
    name: nameB,
    description: "E2E-created assistant B",
    instructions: "Assistant B instructions",
  });
  await pinAssistantByName(page, nameB);
  await expect(
    page.locator('[data-testid^="assistant-["]').filter({ hasText: nameB })
  ).toBeVisible();

  await createAssistant(page, {
    name: nameC,
    description: "E2E-created assistant C",
    instructions: "Assistant C instructions",
  });
  await pinAssistantByName(page, nameC);
  await expect(
    page.locator('[data-testid^="assistant-["]').filter({ hasText: nameC })
  ).toBeVisible();

  // Helper function to get the current order of assistants
  const getAssistantOrder = async () => {
    const assistants = await page.$$('[data-testid^="assistant-["]');
    const names = await Promise.all(
      assistants.map(async (assistant) => {
        const nameEl = await assistant.$("span.line-clamp-1");
        const txt = nameEl ? await nameEl.textContent() : null;
        return (txt || "").trim();
      })
    );
    return names;
  };

  // Get the initial order
  const initialOrder = await getAssistantOrder();

  // Drag second assistant above first
  const secondAssistant = page.locator('[data-testid^="assistant-["]').nth(1);
  const firstAssistant = page.locator('[data-testid^="assistant-["]').nth(0);

  await dragElementAbove(secondAssistant, firstAssistant, page);

  // Check new order
  // wait a second to make sure that the order has been applied
  await page.waitForTimeout(500);
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
  // wait a second to make sure that the order has been applied
  await page.waitForTimeout(500);
  const orderAfterDragDown = await getAssistantOrder();
  expect(orderAfterDragDown[1]).toBe(initialOrder[lastIndex]);

  // Refresh and verify order
  await page.reload();
  const orderAfterRefresh = await getAssistantOrder();
  expect(orderAfterRefresh).toEqual(orderAfterDragDown);
});
