import { test } from "@playwright/test";
import { AdminSkillsPage } from "@tests/e2e/pages/AdminSkillsPage";

for (const fontSize of [16, 32]) {
  test(`upload dialog keeps its controls onscreen at ${fontSize}px text`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    const skills = new AdminSkillsPage(page);
    await skills.goto();
    await page.evaluate((size) => {
      document.documentElement.style.fontSize = `${size}px`;
    }, fontSize);
    const dialog = await skills.openUpload();
    await dialog.expectControlsInsideViewport();
    await dialog.close();
  });
}
