import { useLayoutEffect, useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within } from "storybook/test";
import { SWRConfig, type State } from "swr";
import { ToastProvider } from "@opal/layouts";
import { UserProvider } from "@/providers/UserProvider";
import PluginsPage from "@/views/admin/PluginsPage";
import { MCPServerStatus, type MCPServer } from "@/lib/mcp/types";
import type { ToolSnapshot } from "@/lib/tools/types";
import { Permission } from "@/lib/types";
import messages from "@/i18n/messages/en.json";
import type { ExternalAppAdminResponse } from "@/app/craft/v1/apps/registry";

const apps: ExternalAppAdminResponse[] = [
  {
    id: 7,
    name: "Team service",
    app_type: "CUSTOM",
    enabled: true,
    upstream_url_patterns: ["https://service.onyx.app/*"],
    auth_template: {},
    organization_credentials: {},
    credential_placeholder_keys: [],
    actions: [],
    associated_skills: [],
    is_onyx_managed: false,
  },
];

const servers: MCPServer[] = [
  {
    connection_status: null,
    id: 7,
    name: "Linear",
    description: "Issues and projects from your workspace.",
    server_url: "https://mcp.linear.app/mcp",
    owner: "admin@example.com",
    status: MCPServerStatus.CONNECTED,
    is_public: true,
    groups: [],
    users: [],
    tool_count: 12,
    available_in_craft: true,
    default_chat_enabled: true,
    permissions: { edit: true, authenticate: true, delete: true },
  },
  {
    id: 8,
    connection_status: null,
    name: "Notion",
    description: "Search and update pages in your Notion workspace.",
    server_url: "https://mcp.notion.com/mcp",
    owner: "admin@example.com",
    status: MCPServerStatus.AWAITING_AUTH,
    is_public: true,
    groups: [],
    users: [],
    tool_count: 0,
    available_in_craft: true,
    default_chat_enabled: false,
    permissions: { edit: true, authenticate: true, delete: true },
  },
];

const tools: ToolSnapshot[] = [
  {
    id: 7,
    name: "Team reports",
    display_name: "Team reports",
    description: "Read weekly reports and project summaries.",
    definition: {},
    custom_headers: [],
    in_code_tool_id: null,
    passthrough_auth: false,
    enabled: true,
    chat_selectable: true,
    agent_creation_selectable: true,
    default_enabled: false,
    permissions: { edit: true, authenticate: true, delete: true, toggle: true },
  },
  {
    id: 8,
    name: "Service status",
    display_name: "Service status",
    description: "Look up incidents and scheduled maintenance.",
    definition: {},
    custom_headers: [],
    in_code_tool_id: null,
    passthrough_auth: false,
    enabled: true,
    chat_selectable: true,
    agent_creation_selectable: true,
    default_enabled: false,
    permissions: {},
  },
];

interface PluginsStoryScenario {
  mcp?: "loading" | "error";
  openapi?: "loading" | "error";
  empty?: boolean;
  readOnly?: boolean;
}

interface PluginsStoryProps {
  scenario: PluginsStoryScenario;
}

function json(data: object, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function PluginsStory({ scenario }: PluginsStoryProps) {
  const [ready, setReady] = useState(false);
  const [cache] = useState(() => new Map<string, State>());

  useLayoutEffect(() => {
    const originalFetch = window.fetch;
    const mockFetch: typeof fetch = async (input, init) => {
      const url = new URL(
        input instanceof Request ? input.url : String(input),
        window.location.origin
      );
      if (!url.pathname.startsWith("/api/")) return originalFetch(input, init);
      if (url.pathname === "/api/me")
        return json({
          id: "story-admin",
          email: "admin@example.com",
          is_active: true,
          is_superuser: false,
          is_verified: true,
          account_type: "basic",
          preferences: {},
          team_name: null,
          effective_permissions: scenario.readOnly
            ? []
            : [Permission.FULL_ADMIN_PANEL_ACCESS, Permission.MANAGE_ACTIONS],
          admin_capabilities: scenario.readOnly
            ? []
            : [Permission.MANAGE_ACTIONS],
        });
      if (url.pathname === "/api/settings")
        return json({
          tier: "community",
          ee_features_enabled: false,
          onyx_craft_available: true,
        });
      if (url.pathname === "/api/enterprise-settings") return json({});
      if (url.pathname === "/api/build/admin/apps")
        return json(scenario.empty ? [] : apps);
      if (url.pathname === "/api/build/admin/apps/built-in/options")
        return json([]);
      if (url.pathname === "/api/auth/type")
        return json({ auth_type: "basic", oauth_enabled: true });
      if (url.pathname === "/api/admin/default-assistant/configuration")
        return json({
          tool_ids: [7],
          system_prompt: null,
          default_system_prompt: "",
        });
      if (
        /^\/api\/admin\/mcp\/server\/\d+\/tools\/snapshots$/.test(url.pathname)
      )
        return json(url.pathname.includes("/7/") ? [tools[0]] : []);
      if (url.pathname === "/api/admin/mcp/servers") {
        if (scenario.mcp === "loading") return new Promise<Response>(() => {});
        if (scenario.mcp === "error")
          return json({ detail: "MCP list unavailable" }, 503);
        return json({
          mcp_servers: scenario.empty
            ? []
            : servers.map((server) =>
                scenario.readOnly ? { ...server, permissions: {} } : server
              ),
        });
      }
      if (url.pathname === "/api/tool/openapi") {
        if (scenario.openapi === "loading")
          return new Promise<Response>(() => {});
        if (scenario.openapi === "error")
          return json({ detail: "OpenAPI list unavailable" }, 503);
        return json(
          scenario.empty
            ? []
            : tools.map((tool) =>
                scenario.readOnly ? { ...tool, permissions: {} } : tool
              )
        );
      }
      if (url.pathname === "/api/admin/mcp/probe")
        return new Response(
          JSON.stringify({
            type: "result",
            result: {
              kind: "oauth",
              transport: "STREAMABLE_HTTP",
              discovery: {
                status: "metadata_found",
                supports_automatic_registration: true,
                authorization_endpoint:
                  "https://accounts.example.com/authorize",
                token_endpoint: "https://accounts.example.com/token",
              },
            },
          }) + "\n",
          { headers: { "Content-Type": "application/x-ndjson" } }
        );
      if (url.pathname === "/api/manage/admin/user-group") return json([]);
      return json(
        { detail: `No directory story fixture for ${url.pathname}` },
        404
      );
    };
    window.fetch = mockFetch;
    setReady(true);
    return () => {
      if (window.fetch === mockFetch) window.fetch = originalFetch;
    };
  }, [scenario]);

  return ready ? (
    <SWRConfig
      value={{
        provider: () => cache,
        shouldRetryOnError: false,
        revalidateOnFocus: false,
        dedupingInterval: 0,
      }}
    >
      <UserProvider>
        <ToastProvider>
          <div className="h-screen bg-background-tint-01">
            <PluginsPage />
          </div>
        </ToastProvider>
      </UserProvider>
    </SWRConfig>
  ) : null;
}

const meta = {
  title: "Apps/Plugins/Directory",
  component: PluginsStory,
  parameters: { layout: "fullscreen" },
  args: { scenario: {} },
} satisfies Meta<typeof PluginsStory>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Installed: Story = {};
export const EnabledMCPActions: Story = {
  play: async () => {
    const page = within(document.body);
    const link = await page.findByRole("link", { name: "Manage Linear" });
    const row = link.parentElement;
    if (!row) throw new Error("Plugin row missing");
    await userEvent.click(
      within(row).getByRole("button", {
        name: messages.actions.plugins.controls.disable,
      })
    );
    await expect(
      await page.findByRole("menuitem", {
        name: new RegExp(messages.actions.plugins.controls.disableChat),
      })
    ).toBeVisible();
    await expect(
      await page.findByRole("menuitem", {
        name: new RegExp(messages.actions.plugins.controls.disableCraft),
      })
    ).toBeVisible();
  },
};
export const PluginActions: Story = {
  play: async () => {
    const page = within(document.body);
    const link = await page.findByRole("link", { name: "Manage Team reports" });
    const row = link.parentElement;
    if (!row) throw new Error("Plugin row missing");
    await userEvent.click(
      within(row).getByRole("button", {
        name: messages.actions.plugins.controls.disable,
      })
    );
    await expect(
      await page.findByRole("menuitem", {
        name: new RegExp(messages.actions.plugins.controls.disable),
      })
    ).toBeVisible();
  },
};
export const AddMenu: Story = {
  play: async () => {
    await userEvent.click(
      await within(document.body).findByRole("button", {
        name: messages.actions.plugins.add.label,
      })
    );
  },
};
export const AddCatalog: Story = {
  play: async () => {
    const page = within(document.body);
    await userEvent.click(
      await page.findByRole("button", {
        name: messages.actions.plugins.add.label,
      })
    );
    await userEvent.click(
      await page.findByRole("menuitem", {
        name: messages.actions.plugins.kind.mcp,
      })
    );
  },
};
export const Empty: Story = { args: { scenario: { empty: true } } };
export const Loading: Story = {
  args: { scenario: { mcp: "loading", openapi: "loading" } },
};
export const MCPListError: Story = { args: { scenario: { mcp: "error" } } };
export const OpenAPIListError: Story = {
  args: { scenario: { openapi: "error" } },
};
export const OpenAPIStillLoading: Story = {
  args: { scenario: { openapi: "loading" } },
};
export const ReadOnly: Story = { args: { scenario: { readOnly: true } } };
export const Search: Story = {
  play: async () => {
    const page = within(document.body);
    await page.findByRole("link", { name: "Manage Linear" });
    await userEvent.type(
      page.getByRole("textbox", {
        name: messages.actions.plugins.search.placeholder,
      }),
      "weekly"
    );
    await expect(
      page.getByRole("link", { name: "Manage Team reports" })
    ).toBeVisible();
    await expect(
      page.queryByRole("link", { name: "Manage Linear" })
    ).not.toBeInTheDocument();
  },
};
export const AddCustomMCP: Story = {
  play: async () => {
    const page = within(document.body);
    await userEvent.click(
      await page.findByRole("button", {
        name: messages.actions.plugins.add.label,
      })
    );
    await userEvent.click(
      page.getByRole("menuitem", { name: messages.actions.plugins.kind.mcp })
    );
    await userEvent.click(
      page.getByRole("button", {
        name: messages.actions.plugins.add.mcp,
      })
    );
    await expect(await page.findByRole("dialog")).toBeVisible();
  },
};
