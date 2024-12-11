import { test, expect } from "@playwright/test";
import chromaticSnpashots from "./chromaticSnpashots.json";
import type { Page } from "@playwright/test";

async function verifyAdminPageNavigation(
  page: Page,
  path: string,
  pageTitle: string,
  options?: {
    paragraphText?: string | RegExp;
    buttonName?: string;
    subHeaderText?: string;
  }
) {
  await page.goto(`http://localhost:3000/admin/${path}`);
  await expect(page.locator("h1.text-3xl")).toHaveText(pageTitle);

  if (options?.paragraphText) {
    await expect(page.locator("p.text-sm").nth(0)).toHaveText(
      options.paragraphText
    );
  }

  if (options?.buttonName) {
    await expect(
      page.getByRole("button", { name: options.buttonName })
    ).toHaveCount(1);
  }

  if (options?.subHeaderText) {
    await expect(page.locator("h1.text-lg").nth(0)).toHaveText(
      options.subHeaderText
    );
  }
}

for (const chromaticSnapshot of chromaticSnpashots) {
  test(
    `Admin - ${chromaticSnapshot.name}`,
    {
      tag: "@admin",
    },
    async ({ page }) => {
      await verifyAdminPageNavigation(
        page,
        chromaticSnapshot.path,
        chromaticSnapshot.pageTitle,
        chromaticSnapshot.options
      );
    }
  );
}
