import { test, expect } from "../utils/auth-utils";

test("update search settings", async ({ auth }) => {
  const { page } = await auth("admin");

  await page.goto("http://localhost:3000/admin/indexing/status");
  await page.getByRole("button", { name: "Search Settings" }).click();
  await page.getByRole("button", { name: "Update Search Settings" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Self-hosted" }).click();
  await page.getByText("MixedBread XSmallFastest,").click();
  await page.getByRole("button", { name: "Update Search" }).click();
  await expect(page.locator("body")).toContainText(
    "mixedbread-ai/mxbai-rerank-xsmall-v1"
  );
});
