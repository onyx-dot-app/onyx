import { test } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { AdminOpenApiPluginPage } from "@tests/e2e/pages/AdminOpenApiPluginPage";

const SIMPLE_OPENAPI_SCHEMA = `{
  "openapi": "3.0.0",
  "info": {
    "title": "Test API",
    "version": "1.0.0",
    "description": "A test API for OAuth tool selection"
  },
  "servers": [{ "url": "https://api.example.com" }],
  "paths": {
    "/test": {
      "get": {
        "operationId": "test_operation",
        "summary": "Test operation",
        "description": "A test operation",
        "responses": { "200": { "description": "Success" } }
      }
    }
  }
}`;

let createdIntegrationId: number | null = null;

test.afterAll(async ({ browser }) => {
  const context = await browser.newContext({ storageState: "admin_auth.json" });
  const client = new OnyxApiClient(context.request);
  if (createdIntegrationId !== null) {
    await client.deleteIntegration(createdIntegrationId);
  }
  await context.close();
});

test("OpenAPI app OAuth sign-in settings persist", async ({ page }) => {
  await page.context().clearCookies();
  await loginAs(page, "admin");
  const toolName = `Test API ${Date.now()}`;
  const oauth = {
    authorizationUrl: "https://github.com/login/oauth/authorize",
    tokenUrl: "https://github.com/login/oauth/access_token",
    clientId: "test_client_id_456",
    clientSecret: "test_client_secret_789",
    scopes: "repo, user",
  };
  const schema = SIMPLE_OPENAPI_SCHEMA.replace(
    '"title": "Test API"',
    `"title": "${toolName}"`
  );

  const plugin = new AdminOpenApiPluginPage(page);
  createdIntegrationId = await plugin.createFromSchema(schema, toolName);
  await plugin.configureOAuth(oauth);
  await plugin.expectDetail(toolName);
  await plugin.expectOAuthPersisted(oauth);
});
