import { test } from "@playwright/test";
import { DropdownStoryPage } from "@tests/e2e/pages/DropdownStoryPage";

for (const height of [320, 600]) {
  test(`search stays visible while scrolling an above-trigger dropdown in a ${height}px viewport`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: 600, height });
    const dropdown = new DropdownStoryPage(page);
    await dropdown.open();
    await dropdown.expectAboveTrigger();
    await dropdown.scrollToLastOption();
  });
}
