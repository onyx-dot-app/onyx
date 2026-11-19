import { test, expect } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { AgentEditorPage } from "@tests/e2e/pages/AgentEditorPage";

const LIST_ACTION = "list_reports";
const DELETE_ACTION = "delete_report";
const ARCHIVE_ACTION = "archive_report";

function openApiSpec(title: string): Record<string, unknown> {
  return {
    openapi: "3.0.0",
    info: { title, description: `${title} API`, version: "1.0.0" },
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
      "/reports/{id}/archive": {
        post: {
          operationId: ARCHIVE_ACTION,
          summary: ARCHIVE_ACTION,
          parameters: [
            {
              name: "id",
              in: "path",
              required: true,
              schema: { type: "string" },
            },
          ],
          responses: { "204": { description: "Archived" } },
        },
      },
    },
  };
}

test.describe("Agent integration action settings", () => {
  let integrationId: number | null = null;
  let integrationName: string;
  let agentId: number | null = null;

  test.beforeAll(async ({ browser }) => {
    const context = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const client = new OnyxApiClient(context.request);
    const name = `PW Reports ${Date.now()}`;
    const integration = await client.createIntegration({
      for_organization: true,
      name,
      description: null,
      auth_mode: "none",
      auth_method: null,
      credential_fields: null,
      header_template: null,
      oauth_client: null,
      config: { shape: "openapi", openapi_spec: openApiSpec(name) },
    });
    integrationId = integration.id;
    integrationName = integration.name;
    await client.setIntegrationActionPolicies(integration.id, {
      [ARCHIVE_ACTION]: "blocked",
    });
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

  test("saves a Blocked action setting and shows it after reload", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");

    const editor = new AgentEditorPage(page);
    await editor.goto();
    await editor.fill({ name: `PW Integration Agent ${Date.now()}` });
    await editor.addIntegration(integrationName);
    await editor.expectActionSetting(
      ARCHIVE_ACTION,
      "Use the agent default",
      "Blocked (integration setting)"
    );
    await editor.expectSettingNotOffered(ARCHIVE_ACTION, "Allow");
    await editor.setActionSetting(DELETE_ACTION, "Blocked");
    agentId = await editor.create();

    const client = new OnyxApiClient(page.request);
    const agent = await client.getAssistant(agentId);
    expect(agent.integrations).toHaveLength(1);
    expect(agent.integrations[0]?.action_settings.actions).toEqual({
      [DELETE_ACTION]: "blocked",
    });
    expect(agent.integrations[0]?.action_settings.default ?? "inherit").toBe(
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
      "Use the agent default",
      "Allows (integration setting)"
    );
  });
});
