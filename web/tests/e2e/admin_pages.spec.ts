import { test, expect } from "@chromatic-com/playwright";
import chromaticSnapshots from "./chromaticSnapshots.json";
import type { Page } from "@playwright/test";

test.use({ storageState: "admin_auth.json" });

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

  try {
    await expect(page.locator("h1.text-3xl")).toHaveText(pageTitle, {
      timeout: 10000,
    });
  } catch (error) {
    console.error(
      `Failed to find h1 with text "${pageTitle}" for path "${path}"`
    );
    // NOTE: This is a temporary measure for debugging the issue
    console.error(await page.content());
    throw error;
  }

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
}

for (const chromaticSnapshot of chromaticSnapshots) {
  test(`Admin - ${chromaticSnapshot.name}`, async ({ page }) => {
    await verifyAdminPageNavigation(
      page,
      chromaticSnapshot.path,
      chromaticSnapshot.pageTitle,
      chromaticSnapshot.options
    );
  });
}
