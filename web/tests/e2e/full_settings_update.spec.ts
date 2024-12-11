import { test, expect } from "@playwright/test";

test("test", async ({ page }) => {
  await page.goto("http://localhost:3000/admin/configuration/search");
  await page.getByRole("button", { name: "Update Search Settings" }).click();
  await page.getByRole("button", { name: "Self-hosted", exact: true }).click();
  await page.getByRole("button", { name: "Select Model" }).nth(1).click();
  await page.getByRole("button", { name: "Yes" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await page
    .getByRole("button", { name: "Continue with intfloat/e5-" })
    .click();
  await page.getByText("MixedBread BaseBalanced").click();
  await page.getByRole("button", { name: "Advanced" }).click();
  await page.getByLabel("Disable Rerank for Streaming").check();
  await page.getByRole("button", { name: "Re-index" }).click();
  await page.getByRole("button", { name: "Re-index" }).click();
  await page.goto("http://localhost:3000/admin/configuration/search");
  await page.getByText("intfloat/e5-base-v2").click();
  await page.getByText("mixedbread-ai/mxbai-rerank-").click();
  await page.getByText("Disabled").click();
});
