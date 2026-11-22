import {
  expect,
  test,
  type APIRequestContext,
  type Browser,
} from "@playwright/test";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { CustomizePluginPage } from "@tests/e2e/pages/CustomizePluginPage";
import { pluginZip, zipFile } from "@tests/e2e/utils/plugins";
import { deleteSkill, uniqueSkillName } from "@tests/e2e/utils/skills";
import type {
  AuthMode,
  InstallationPolicy,
  IntegrationCreate,
} from "@/lib/integrations/types";

test.describe("Plugin upload", () => {
  test.describe.configure({ mode: "serial" });

  const suffix = uniqueSkillName("pw-plugin");
  const base = `https://example.com/${suffix}`;
  const integrationIds: Record<string, number> = {};
  const pluginIds: string[] = [];

  function mcpIntegration(
    name: string,
    serverUrl: string,
    forOrganization: boolean,
    authMode: AuthMode
  ): IntegrationCreate {
    return {
      for_organization: forOrganization,
      name,
      description: "Plugin upload e2e",
      auth_mode: authMode,
      auth_method: "api_key",
      credential_fields: [{ key: "api_key", label: "API Key", secret: true }],
      header_template: { Authorization: "Bearer {api_key}" },
      oauth_client: null,
      config: {
        shape: "mcp_server",
        server_url: serverUrl,
        transport: "STREAMABLE_HTTP",
      },
    };
  }

  async function withAdmin<T>(
    browser: Browser,
    run: (client: OnyxApiClient, request: APIRequestContext) => Promise<T>
  ): Promise<T> {
    const context = await browser.newContext({
      storageState: "admin_auth.json",
    });
    try {
      return await run(new OnyxApiClient(context.request), context.request);
    } finally {
      await context.close();
    }
  }

  function servers(): Record<string, Record<string, string>> {
    return {
      "pw-on": { type: "http", url: `${base}/on` },
      "pw-off": {
        type: "http",
        url: `${base.replace("example", "EXAMPLE")}/off/`,
      },
      "pw-sign-in": { type: "http", url: `${base}/sign-in` },
      "pw-disabled": { type: "http", url: `${base}/disabled` },
      "pw-missing": { type: "sse", url: `${base}/missing` },
      "pw-local": { command: "npx", args: "pw-local-server" },
    };
  }

  test.beforeAll(async ({ browser }) => {
    await withAdmin(browser, async (admin, request) => {
      const shared: [string, string, AuthMode, InstallationPolicy][] = [
        ["pw-on", `${base}/on`, "shared", "DEFAULT"],
        ["pw-off", `${base}/off`, "shared", "AVAILABLE"],
        ["pw-sign-in", `${base}/sign-in`, "individual", "DEFAULT"],
        ["pw-disabled", `${base}/disabled`, "shared", "DEFAULT"],
      ];
      for (const [need, url, authMode, policy] of shared) {
        const created = await admin.createIntegration(
          mcpIntegration(`PW Plugin ${need} ${suffix}`, url, true, authMode)
        );
        integrationIds[need] = created.id;
        await admin.setIntegrationInstallationPolicy(created.id, policy);
        if (authMode === "shared") {
          const connect = await request.put(
            `/api/admin/integrations/${created.id}/organization-connection`,
            { data: { fields: { api_key: "pw-key" } } }
          );
          expect(connect.ok(), await connect.text()).toBeTruthy();
        }
      }
      const turnedOff = await request.patch(
        `/api/admin/integrations/${integrationIds["pw-disabled"]}`,
        { data: { enabled: false } }
      );
      expect(turnedOff.ok(), await turnedOff.text()).toBeTruthy();
    });
  });

  test.afterAll(async ({ browser }) => {
    await withAdmin(browser, async (admin, request) => {
      for (const id of pluginIds) await deleteSkill(request, id);
      for (const id of Object.values(integrationIds))
        await admin.deleteIntegration(id);
    });
  });

  test("a plugin zip previews, saves, and a second upload adds a version", async ({
    page,
  }) => {
    const name = uniqueSkillName("pw-plugin");
    const review = uniqueSkillName("review");
    const zip = await pluginZip({
      name,
      skills: [review, uniqueSkillName("summarize")],
      mcpServers: servers(),
      extra: { "commands/deploy.md": "Deploy." },
    });
    const plugins = new CustomizePluginPage(page);

    await plugins.openUploadDialog();
    await plugins.chooseZip(zip);
    await plugins.expectSaveLine(`New plugin: ${name}`);
    await plugins.expectPreviewText("Skills · 2");
    await plugins.expectPreviewText("Integrations · 6");
    await plugins.expectPreviewText("Commands");
    const firstId = await plugins.saveUpload();
    pluginIds.push(firstId);
    await expect(page).toHaveURL(/\?tab=integrations$/);

    await plugins.openUploadDialog();
    await plugins.chooseZip(
      await pluginZip({
        name,
        version: "1.1.0",
        skills: [review],
        mcpServers: servers(),
      })
    );
    await plugins.expectSaveLine(`Updates ${name} to Onyx version 2`);
    await plugins.setSaveAsNew(true);
    await plugins.expectSaveLine(`New plugin: ${name}-2`);
    await plugins.setSaveAsNew(false);
    await plugins.expectSaveLine(`Updates ${name} to Onyx version 2`);
    expect(await plugins.saveUpload()).toBe(firstId);
    await plugins.expectTab("Skills · 1");
  });

  test("a bad zip shows the reason, and a skill zip keeps the skill flow", async ({
    page,
  }) => {
    const plugins = new CustomizePluginPage(page);
    await plugins.openUploadDialog();
    await plugins.chooseZip(
      await zipFile("bad.zip", {
        ".claude-plugin/plugin.json": JSON.stringify({ name: "Bad Name" }),
        "skills/review/SKILL.md": "---\nname: review\ndescription: x\n---\n",
      })
    );
    await plugins.expectUploadError(
      "The plugin name 'Bad Name' in .claude-plugin/plugin.json must use only lowercase letters"
    );

    await plugins.chooseZip(
      await zipFile("empty.zip", {
        ".claude-plugin/plugin.json": JSON.stringify({ name: "pw-empty" }),
      })
    );
    await plugins.expectUploadError(
      "This plugin has no skill and no MCP server."
    );

    await plugins.chooseZip(
      await zipFile("skill.zip", {
        "SKILL.md": "---\nname: pw-skill-only\ndescription: x\n---\n\nDo it.\n",
      })
    );
    await plugins.expectPreviewText("This upload is a skill");
  });

  test("the Integrations tab shows each need state with its action", async ({
    page,
  }) => {
    const plugins = new CustomizePluginPage(page);
    await plugins.goto(pluginIds[0]!, "integrations");
    await plugins.expectNeed("pw-on", "On");
    await plugins.expectNeed("pw-sign-in", "Not signed in");
    await plugins.expectNeedButton(
      "pw-sign-in",
      /^Connect PW Plugin pw-sign-in/
    );
    await plugins.expectNeed(
      "pw-disabled",
      "Turned off",
      "Turned off by your admin"
    );
    await plugins.expectNeed(
      "pw-local",
      "Not supported",
      "Not supported in Onyx"
    );
    await plugins.expectNeed("pw-missing", "Not added");

    await plugins.expectNeed("pw-off", "On");
    await new OnyxApiClient(page.request).setIntegrationEnabled(
      integrationIds["pw-off"]!,
      false
    );
    await page.reload();
    await plugins.expectNeed("pw-off", "Off");
    await plugins.turnOnNeed("pw-off");
    await plugins.expectNeed("pw-off", "On");

    await plugins.addNeedIntegration("pw-missing");
    await plugins.expectIntegrationPrefill("pw-missing", `${base}/missing`);
  });
});
