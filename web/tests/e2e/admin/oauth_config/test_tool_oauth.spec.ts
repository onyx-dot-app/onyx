import { test } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { AdminOpenApiPluginPage } from "@tests/e2e/pages/AdminOpenApiPluginPage";
import { AgentEditorPage } from "@tests/e2e/pages/AgentEditorPage";

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

let createdAssistantId: number | null = null;
let createdToolId: number | null = null;

test.afterAll(async ({ browser }) => {
  const context = await browser.newContext({ storageState: "admin_auth.json" });
  const client = new OnyxApiClient(context.request);
  if (createdAssistantId !== null) {
    await client.deleteAgent(createdAssistantId);
  }
  if (createdToolId !== null) {
    await client.deleteCustomTool(createdToolId);
  }
  await context.close();
});

test("OpenAPI plugin OAuth persists and remains available to agents", async ({
  page,
}) => {
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
  createdToolId = await plugin.createFromSchema(schema, toolName);
  await plugin.configureOAuth(oauth);
  // Update closes the modal; reopen it to check the saved settings.
  await plugin.open();
  await plugin.expectDetail(toolName);
  await plugin.expectOAuthPersisted(oauth);

  const agent = new AgentEditorPage(page);
  await agent.goto();
  await agent.fill({
    name: `Test Assistant ${Date.now()}`,
    description: "Assistant with OAuth tool",
    instructions: "Use the tool when needed",
  });
  await agent.enableOpenApiTool(createdToolId);
  createdAssistantId = await agent.create();
});
