import { test, expect } from "@chromatic-com/playwright";

test.use({ storageState: "admin_auth.json" });

test("Admin - OAuth Redirect - Missing Code", async ({ page }) => {
  await page.goto(
    "http://localhost:3000/admin/connectors/slack/oauth/callback?state=xyz"
  );

  await expect(page.locator("p.text-text-500")).toHaveText(
    "Missing authorization code."
  );
});

test("Admin - OAuth Redirect - Missing State", async ({ page }) => {
  await page.goto(
    "http://localhost:3000/admin/connectors/slack/oauth/callback?code=123"
  );

  await expect(page.locator("p.text-text-500")).toHaveText(
    "Missing state parameter."
  );
});

test("Admin - OAuth Redirect - Invalid Connector", async ({ page }) => {
  await page.goto(
    "http://localhost:3000/admin/connectors/invalid-connector/oauth/callback?code=123&state=xyz"
  );

  await expect(page.locator("p.text-text-500")).toHaveText(
    "invalid_connector is not a valid source type."
  );
});
