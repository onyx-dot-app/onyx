import { test, expect } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { AgentEditorPage } from "@tests/e2e/pages/AgentEditorPage";

const LIST_ACTION = "list_reports";
const DELETE_ACTION = "delete_report";

function openApiSpec(title: string): Record<string, unknown> {
  return {
    openapi: "3.0.0",
    info: { title, version: "1.0.0" },
    servers: [{ url: "https://api.example.com" }],
    paths: {
      "/reports": {
        get: {
          operationId: LIST_ACTION,
          summary: LIST_ACTION,
          responses: { "200": { description: "Success" } },
        },
      },
      "/reports/{id}": {
        delete: {
          operationId: DELETE_ACTION,
          summary: DELETE_ACTION,
          parameters: [
            {
              name: "id",
              in: "path",
              required: true,
              schema: { type: "string" },
            },
          ],
          responses: { "204": { description: "Deleted" } },
        },
      },
    },
  };
}

test.describe("Agent plugin action settings", () => {
  let integrationId: number | null = null;
  let pluginName: string;
  let agentId: number | null = null;

  test.beforeAll(async ({ browser }) => {
    const context = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const client = new OnyxApiClient(context.request);
    const name = `PW Reports ${Date.now()}`;
    const integration = await client.createOpenApiIntegration(
      name,
      openApiSpec(name)
    );
    integrationId = integration.id;
    pluginName = integration.plugins[0]?.plugin_name ?? name;
    await context.close();
  });

  test.afterAll(async ({ browser }) => {
    const context = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const client = new OnyxApiClient(context.request);
    if (agentId !== null) await client.deleteAgent(agentId);
    if (integrationId !== null) await client.deleteIntegration(integrationId);
    await context.close();
  });

  test("an agent with one action set to Blocked does not offer it", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");

    const editor = new AgentEditorPage(page);
    await editor.goto();
    await editor.fill({ name: `PW Plugin Agent ${Date.now()}` });
    await editor.addPlugin(pluginName);
    await editor.setActionSetting(DELETE_ACTION, "Blocked");
    agentId = await editor.create();

    const client = new OnyxApiClient(page.request);
    const agent = await client.getAssistant(agentId);
    expect(agent.plugins).toHaveLength(1);
    expect(agent.plugins[0]?.action_settings.actions).toEqual({
      [DELETE_ACTION]: "blocked",
    });
    expect(agent.plugins[0]?.action_settings.default ?? "inherit").toBe(
      "inherit"
    );

    await editor.gotoEdit(agentId);
    await editor.expectActionSetting(
      DELETE_ACTION,
      "Blocked",
      "Blocked (agent setting)"
    );
    await editor.expectActionSetting(
      LIST_ACTION,
      "Use the integration setting",
      "Allows (integration setting)"
    );
  });
});
