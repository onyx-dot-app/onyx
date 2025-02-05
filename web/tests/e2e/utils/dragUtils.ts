import { Locator, Page } from "@playwright/test";

/**
 * Drag "source" above (higher Y) "target" by using mouse events.
 * Positions the cursor on the lower half of source, then moves to the top half of the target.
 */
export async function dragElementAbove(
  sourceLocator: Locator,
  targetLocator: Locator,
  page: Page
) {
  // Get bounding boxes
  const sourceBB = await sourceLocator.boundingBox();
  const targetBB = await targetLocator.boundingBox();
  if (!sourceBB || !targetBB) {
    throw new Error("Source/target bounding boxes not found.");
  }

  // Move over source, press mouse down
  await page.mouse.move(
    sourceBB.x + sourceBB.width / 2,
    sourceBB.y + sourceBB.height * 0.75 // Move to 3/4 down the source element
  );
  await page.mouse.down();

  // Move to a point slightly above the target's center
  await page.mouse.move(
    targetBB.x + targetBB.width / 2,
    targetBB.y + targetBB.height * 0.1, // Move to 1/10 down the target element
    { steps: 20 } // Increase steps for smoother drag
  );
  await page.mouse.up();

  // Increase wait time for DnD transitions
  await page.waitForTimeout(200);
}

/**
 * Drag "source" below (higher Y → lower Y) "target" using mouse events.
 */
export async function dragElementBelow(
  sourceLocator: Locator,
  targetLocator: Locator,
  page: Page
) {
  // Get bounding boxes
  const sourceBB = await targetLocator.boundingBox();
  const targetBB = await sourceLocator.boundingBox();
  if (!sourceBB || !targetBB) {
    throw new Error("Source/target bounding boxes not found.");
  }

  // Move over source, press mouse down
  await page.mouse.move(
    sourceBB.x + sourceBB.width / 2,
    sourceBB.y + sourceBB.height * 0.25 // Move to 1/4 down the source element
  );
  await page.mouse.down();

  // Move to a point well below the target's bottom edge
  await page.mouse.move(
    targetBB.x + targetBB.width / 2,
    targetBB.y + targetBB.height + 50, // Move 50 pixels below the target element
    { steps: 50 } // Keep the same number of steps for smooth drag
  );

  // Hold for a moment to ensure the drag is registered
  await page.waitForTimeout(500);

  await page.mouse.up();

  // Wait for DnD transitions and potential animations
  await page.waitForTimeout(1000);
}
