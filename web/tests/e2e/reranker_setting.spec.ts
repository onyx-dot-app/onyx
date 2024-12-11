import { test, expect } from "@playwright/test";

test("test", async ({ page }) => {
  await page.goto("http://localhost:3000/admin/configuration/search");
  await page.getByRole("button", { name: "Update Search Settings" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Self-hosted" }).click();
  await page.getByText("MixedBread XSmallFastest,").click();
  await page.getByRole("button", { name: "Update Search" }).click();
  await expect(page.locator("body")).toContainText(
    "mixedbread-ai/mxbai-rerank-xsmall-v1"
  );
});
