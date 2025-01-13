import { test, expect } from "@chromatic-com/playwright";

test(
  "Admin - OAuth Redirect - Missing Code",
  {
    tag: "@admin",
  },
  async ({ page }, testInfo) => {
    await page.goto(
      "http://localhost:3000/admin/connectors/slack/oauth/callback?state=xyz"
    );

    await expect(page.locator("p.text-text-500")).toHaveText(
      "Missing authorization code."
    );
  }
);

test(
  "Admin - OAuth Redirect - Missing State",
  {
    tag: "@admin",
  },
  async ({ page }, testInfo) => {
    await page.goto(
      "http://localhost:3000/admin/connectors/slack/oauth/callback?code=123"
    );

    await expect(page.locator("p.text-text-500")).toHaveText(
      "Missing state parameter."
    );
  }
);

test(
  "Admin - OAuth Redirect - Invalid Connector",
  {
    tag: "@admin",
  },
  async ({ page }, testInfo) => {
    await page.goto(
      "http://localhost:3000/admin/connectors/invalid-connector/oauth/callback?code=123&state=xyz"
    );

    await expect(page.locator("p.text-text-500")).toHaveText(
      "invalid_connector is not a valid source type."
    );
  }
);

test(
  "Admin - OAuth Redirect - No Session",
  {
    tag: "@admin",
  },
  async ({ page }, testInfo) => {
    await page.goto(
      "http://localhost:3000/admin/connectors/slack/oauth/callback?code=123&state=xyz"
    );

    await expect(page.locator("p.text-text-500")).toHaveText(
      "An error occurred during the OAuth process. Please try again."
    );
  }
);
