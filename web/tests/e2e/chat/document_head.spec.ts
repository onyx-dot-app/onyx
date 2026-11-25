import { test } from "@playwright/test";
import { DocumentHead } from "@tests/e2e/pages/DocumentHead";

test.describe("Document head", () => {
  for (const path of ["/app", "/auth/login"]) {
    test(`${path} allows zoom and has a title`, async ({ page }) => {
      await page.goto(path);
      const head = new DocumentHead(page);
      await head.expectZoomAllowed();
      await head.expectTitle(/\S/);
    });
  }
});
