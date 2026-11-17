import { test } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import {
  McpServerProcess,
  startMcpApiKeyServer,
} from "@tests/e2e/utils/mcpServer";
import { AdminIntegrationsPage } from "@tests/e2e/pages/AdminIntegrationsPage";
import { AdminIntegrationDetailPage } from "@tests/e2e/pages/AdminIntegrationDetailPage";
import { AdminMcpServersPage } from "@tests/e2e/pages/AdminMcpServersPage";
import { AdminOpenApiPluginPage } from "@tests/e2e/pages/AdminOpenApiPluginPage";

const API_KEY = process.env.MCP_API_KEY || "test-api-key-12345";
const PORT = Number(process.env.MCP_INTEGRATIONS_TEST_PORT || "8015");
const MCP_API_KEY_TEST_URL = process.env.MCP_API_KEY_TEST_URL;
const MCP_TOOL = "tool_0";

function openApiSchema(title: string): string {
  return JSON.stringify({
    openapi: "3.0.0",
    info: { title, description: `${title} API`, version: "1.0.0" },
    servers: [{ url: "https://api.example.com" }],
    paths: {
      "/reports": {
        get: {
          operationId: "list_reports",
          summary: "List reports",
          responses: { "200": { description: "Success" } },
        },
      },
    },
  });
}

test.describe("Admin integrations", () => {
  test.describe.configure({ mode: "serial" });

  let server: McpServerProcess | null = null;
  let serverUrl: string;
  const createdIds: number[] = [];

  test.beforeAll(async () => {
    if (MCP_API_KEY_TEST_URL) {
      serverUrl = MCP_API_KEY_TEST_URL;
    } else {
      server = await startMcpApiKeyServer({ port: PORT, apiKey: API_KEY });
      serverUrl = `http://${server.address.host}:${server.address.port}/mcp`;
    }
  });

  test.afterAll(async ({ browser }) => {
    const context = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const client = new OnyxApiClient(context.request);
    for (const id of createdIds) await client.deleteIntegration(id);
    await context.close();
    await server?.stop();
  });

  test("adds an MCP server and an OpenAPI app, sets an action to Ask, and lists both", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    const suffix = Date.now();
    const mcpName = `PW MCP ${suffix}`;
    const openApiName = `PW Reports ${suffix}`;
    const integrations = new AdminIntegrationsPage(page);
    const detail = new AdminIntegrationDetailPage(page);

    // MCP server with one organization API key.
    const mcp = new AdminMcpServersPage(page);
    await mcp.goto();
    await mcp.openAddServerModal();
    await integrations.fillMcpServer({
      name: mcpName,
      url: serverUrl,
    });
    await integrations.selectSignIn(
      "One account for the organization",
      "API key"
    );
    await integrations.chooseOwner("For the organization");
    createdIds.push(await integrations.submit());
    await detail.connectOrganization({ "api key": API_KEY });
    await detail.openTab("Actions");
    await detail.refreshActions();
    await detail.setActionPolicy(MCP_TOOL, "Ask");
    await detail.saveActions();
    await detail.expectSetByAdmin(MCP_TOOL);

    // OpenAPI app with no sign-in.
    const openApi = new AdminOpenApiPluginPage(page);
    createdIds.push(
      await openApi.createFromSchema(openApiSchema(openApiName), openApiName)
    );

    await integrations.goto();
    await integrations.expectIntegrationVisible(mcpName);
    await integrations.expectIntegrationVisible(openApiName);
  });
});
