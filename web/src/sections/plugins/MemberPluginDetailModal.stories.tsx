import type { Meta, StoryObj } from "@storybook/react-vite";
import { MCPConnectionStatus } from "@/lib/mcp/types";
import { expect, userEvent, within } from "storybook/test";
import { NextIntlClientProvider } from "next-intl";
import { SWRConfig } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import MemberPluginDetailModal from "@/sections/plugins/MemberPluginDetailModal";
import {
  memberServer,
  memberTool,
  storedMcpTool,
  memberPluginMessages,
  memberApp,
} from "@/sections/plugins/__tests__/memberPluginFixtures";
import {
  builtinFixture,
  customFixture,
} from "@/lib/skills/__fixtures__/picker";

const appSkills = {
  builtins: [
    builtinFixture({
      name: "GitHub workflow",
      description: "Read issues and prepare repository updates.",
      enabled: true,
      external_app: {
        external_app_id: 7,
        name: "GitHub",
        enabled: true,
        ready: true,
      },
    }),
  ],
  customs: [
    customFixture({
      name: "Release digest",
      description: "Summarize changes for the next release.",
      enabled: false,
      external_app: {
        external_app_id: 7,
        name: "GitHub",
        enabled: true,
        ready: true,
      },
    }),
  ],
};

const tools = [
  {
    ...storedMcpTool,
    description:
      "Search issues across the projects you can access. Filter by team, assignee, project, status, priority, or a date range. Results include the issue title, description, status, assignee, and a link to the original issue. Use the issue identifier to retrieve its complete history before preparing a project update.",
  },
  memberTool({
    id: 72,
    mcp_server_id: 7,
    name: "get_project",
    display_name: "Get project",
    description:
      "Retrieve a project's description, owner, milestones, and current status. Include archived projects when you need historical context for a planning discussion.",
  }),
  memberTool({
    id: 73,
    mcp_server_id: 7,
    name: "list_comments",
    display_name: "List issue comments",
    description:
      "Read the discussion attached to an issue. Comments include their author and creation date, with the most recent replies first. Follow the next-page cursor to read older replies.",
  }),
];

const meta = {
  title: "Apps/Plugins/Member MCP Details",
  component: MemberPluginDetailModal,
  beforeEach: () => {
    const originalFetch = globalThis.fetch;
    const preferences = { enabled_in_chat: true, enabled_in_craft: true };
    globalThis.fetch = async (input, init) => {
      if (String(input).startsWith("/api/build/action-policies/")) {
        return Response.json({
          gated_app_id: 7,
          kind: "mcp_server",
          target_id: 7,
          name: "Linear",
          enabled: null,
          users_can_manage_policies: true,
          actions: [
            {
              action_id: "search",
              normalised_name: "Search issues",
              description: "Find issues across your projects.",
              effective_policy: "ALWAYS",
              workspace_policy: "ASK",
              stored_policy: "ALWAYS",
              editable: true,
              lock_reason: null,
            },
            {
              action_id: "delete",
              normalised_name: "Delete issues",
              description: "Delete an issue permanently.",
              effective_policy: "DENY",
              workspace_policy: "DENY",
              stored_policy: null,
              editable: false,
              lock_reason: "workspace_disabled",
            },
          ],
        });
      }
      if (String(input) === "/api/skills") return Response.json(appSkills);
      if (String(input) === "/api/settings")
        return Response.json({
          onyx_craft_enabled: true,
          onyx_craft_available: true,
        });
      if (String(input) === "/api/enterprise-settings")
        return Response.json({});
      if (
        (String(input) === "/api/mcp/server/7/preferences" ||
          String(input) === "/api/tool/7/preferences") &&
        init?.method === "PATCH"
      ) {
        const body: unknown = JSON.parse(String(init.body));
        if (typeof body === "object" && body !== null) {
          if (
            "enabled_in_chat" in body &&
            typeof body.enabled_in_chat === "boolean"
          )
            preferences.enabled_in_chat = body.enabled_in_chat;
          if (
            "enabled_in_craft" in body &&
            typeof body.enabled_in_craft === "boolean"
          )
            preferences.enabled_in_craft = body.enabled_in_craft;
        }
        return Response.json(
          String(input).startsWith("/api/tool/")
            ? { enabled_in_chat: preferences.enabled_in_chat }
            : preferences
        );
      }
      return originalFetch(input, init);
    };
    return () => {
      globalThis.fetch = originalFetch;
    };
  },
  parameters: { layout: "fullscreen" },
  decorators: [
    (Story, context) => (
      <NextIntlClientProvider locale="en" messages={memberPluginMessages}>
        <SWRConfig
          value={{
            provider: () =>
              new Map([
                [
                  SWR_KEYS.mcpServers,
                  {
                    data: {
                      mcp_servers:
                        context.args.plugin.kind === "mcp"
                          ? [context.args.plugin.server]
                          : [],
                    },
                  },
                ],
                [
                  SWR_KEYS.tools,
                  {
                    data:
                      context.args.plugin.kind === "openapi"
                        ? [context.args.plugin.tool]
                        : [],
                  },
                ],
                [
                  SWR_KEYS.mcpServersCraft,
                  {
                    data: {
                      mcp_servers:
                        context.args.plugin.kind === "mcp"
                          ? [context.args.plugin.server]
                          : [],
                    },
                  },
                ],
              ]),
          }}
        >
          <Story />
        </SWRConfig>
      </NextIntlClientProvider>
    ),
  ],
  args: {
    open: true,
    plugin: {
      kind: "mcp",
      server: memberServer({
        user_enabled_in_chat: true,
        user_enabled_in_craft: true,
      }),
      tools,
      connection: { kind: "connected", ownership: "user" },
    },
    onClose: () => undefined,
    onConnect: () => undefined,
    onUseInChat: () => undefined,
    onDisconnected: () => undefined,
  },
} satisfies Meta<typeof MemberPluginDetailModal>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Connection: Story = {};

export const Tools: Story = {
  play: async () => {
    const page = within(document.body);
    await userEvent.click(await page.findByRole("tab", { name: "Tools" }));
    await expect(
      page.getByText(/Search issues across the projects you can access/)
    ).toBeVisible();
  },
};

export const NeedsAccount: Story = {
  args: {
    plugin: {
      kind: "mcp",
      server: memberServer({
        connection_status: MCPConnectionStatus.NOT_CONNECTED,
      }),
      tools,
      connection: { kind: "oauth" },
    },
  },
};

export const CraftConnection: Story = {
  args: { surface: "craft" },
};

export const CraftAppConnection: Story = {
  args: {
    plugin: {
      kind: "external-app",
      app: memberApp({ name: "GitHub", authenticated: true }),
      connection: { kind: "connected", ownership: "user" },
    },
  },
};

export const CraftAppSkills: Story = {
  args: CraftAppConnection.args,
  play: async () => {
    const page = within(document.body);
    await userEvent.click(await page.findByRole("tab", { name: "Skills" }));
    await expect(await page.findByText("Release digest")).toBeVisible();
  },
};

export const CraftAppNeedsAccount: Story = {
  args: {
    plugin: {
      kind: "external-app",
      app: memberApp({ name: "GitHub", authenticated: false }),
      connection: { kind: "oauth" },
    },
  },
};

export const DisconnectConfirmation: Story = {
  play: async () => {
    const page = within(document.body);
    await userEvent.click(
      await page.findByRole("button", { name: "Disconnect account" })
    );
    await expect(page.getByText("Disconnect Linear?")).toBeVisible();
  },
};

export const OpenAPIConnection: Story = {
  args: {
    plugin: {
      kind: "openapi",
      tool: memberTool({
        name: "GitHub User API",
        display_name: "GitHub User API",
        description: "Fetch GitHub user info",
        definition: {
          servers: [{ url: "https://api.github.com" }],
          paths: {
            "/user": {
              get: {
                operationId: "getAuthenticatedUser",
                summary: "Get the authenticated GitHub user",
              },
            },
          },
        },
      }),
      connection: { kind: "connected", ownership: "none" },
    },
  },
};

export const OpenAPITools: Story = {
  args: OpenAPIConnection.args,
  play: async () => {
    const page = within(document.body);
    await userEvent.click(await page.findByRole("tab", { name: "Tools" }));
    await expect(page.getByText("getAuthenticatedUser")).toBeVisible();
    await expect(page.getByText("GET")).toBeVisible();
  },
};

export const ApprovalSettings: Story = {
  args: { initialTab: "approvals", surface: "craft" },
  play: async () => {
    const page = within(document.body);
    const action = await page.findByRole("group", { name: "Search issues" });
    await expect(page.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.click(within(action).getByRole("button", { name: "Ask" }));
    await expect(page.getByRole("button", { name: "Save" })).toBeEnabled();
  },
};
