import { MCPConnectionStatus } from "@/lib/mcp/types";
import { useLayoutEffect, useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within } from "storybook/test";
import { SWRConfig, type State } from "swr";
import { NextIntlClientProvider } from "next-intl";
import { UserProvider } from "@/providers/UserProvider";
import {
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
} from "@/lib/mcp/types";
import { Permission } from "@/lib/types";
import MemberPluginsPage from "@/views/PluginsPage";
import {
  jsonResponse,
  memberServer,
  memberTool,
  storedMcpTool,
  memberPluginMessages,
  memberApp,
} from "@/sections/plugins/__tests__/memberPluginFixtures";

type MemberScenario =
  | "ready"
  | "empty"
  | "source-error"
  | "account-loading"
  | "manager"
  | "popup-blocked";

interface MemberPluginsStoryProps {
  scenario: MemberScenario;
  initialFilter?: "all" | "connected" | "needsSignIn";
  surface?: "all" | "craft";
}

function MemberPluginsStory({
  scenario,
  initialFilter,
  surface,
}: MemberPluginsStoryProps) {
  const [ready, setReady] = useState(false);
  const [cache] = useState(() => new Map<string, State>());

  useLayoutEffect(() => {
    const originalFetch = window.fetch;
    const originalOpen = window.open;
    let credentialsSaved = false;
    let oauthConnected = true;
    if (scenario === "popup-blocked") window.open = () => null;

    const mockFetch: typeof fetch = async (input, init) => {
      const path = new URL(
        input instanceof Request ? input.url : String(input),
        window.location.origin
      ).pathname;
      if (!path.startsWith("/api/")) return originalFetch(input, init);
      if (path === "/api/me")
        return jsonResponse({
          id: "story-member",
          email: "member@example.com",
          is_active: true,
          is_superuser: false,
          is_verified: true,
          account_type: "basic",
          preferences: {},
          team_name: null,
          effective_permissions:
            scenario === "manager" ? [Permission.MANAGE_ACTIONS] : [],
          admin_capabilities:
            scenario === "manager" ? [Permission.MANAGE_ACTIONS] : [],
        });
      if (path === "/api/settings")
        return jsonResponse({
          tier: "community",
          ee_features_enabled: false,
          onyx_craft_available: true,
          onyx_craft_enabled: true,
        });
      if (path === "/api/enterprise-settings") return jsonResponse({});
      if (path === "/api/skills")
        return jsonResponse({ builtins: [], customs: [] });
      if (path === "/api/auth/type")
        return jsonResponse({ auth_type: "basic", oauth_enabled: true });
      if (path === "/api/build/apps")
        return jsonResponse(
          scenario === "empty"
            ? []
            : [
                memberApp({ authenticated: true }),
                memberApp({
                  id: 13,
                  name: "Workspace Slack",
                  app_type: "SLACK",
                }),
              ]
        );
      if (path === "/api/mcp/servers" || path === "/api/mcp/servers/craft") {
        if (scenario === "source-error")
          return jsonResponse({ detail: "MCP unavailable" }, 503);
        return jsonResponse({
          mcp_servers:
            scenario === "empty"
              ? []
              : [
                  memberServer({ craft_connected: true }),
                  memberServer({
                    id: 8,
                    name: "Support desk",
                    description: "Look up tickets and customer conversations.",
                    server_url: "https://support.example.com/mcp",
                    auth_type: MCPAuthenticationType.API_TOKEN,
                    auth_template: {
                      required_fields: ["api_key"],
                      headers: { Authorization: "Bearer {api_key}" },
                    },
                    connection_status: credentialsSaved
                      ? MCPConnectionStatus.CONNECTED
                      : MCPConnectionStatus.NOT_CONNECTED,
                    craft_connected: credentialsSaved,
                  }),
                  memberServer({
                    id: 9,
                    name: "Notion",
                    description: "Find pages and notes from your workspace.",
                    server_url: "https://mcp.notion.com/mcp",
                    connection_status: MCPConnectionStatus.NOT_CONNECTED,
                    craft_connected: false,
                  }),
                  memberServer({
                    id: 10,
                    name: "Workspace status",
                    craft_connected: true,
                    description:
                      "Read incidents through the workspace connection.",
                    server_url: "https://status.example.com/mcp",
                    auth_type: MCPAuthenticationType.API_TOKEN,
                    auth_performer: MCPAuthenticationPerformer.ADMIN,
                  }),
                  memberServer({
                    id: 11,
                    name: "Public handbook",
                    description: "Read public reference material.",
                    server_url: "https://handbook.example.com/mcp",
                    auth_type: MCPAuthenticationType.NONE,
                    available_in_craft: false,
                  }),
                  memberServer({
                    id: 12,
                    name: "Session API",
                    craft_connected: true,
                    description: "Use the account from your current sign-in.",
                    server_url: "https://session.example.com/mcp",
                    auth_type: MCPAuthenticationType.PT_OAUTH,
                  }),
                ],
        });
      }
      if (path === "/api/tool")
        return jsonResponse(
          scenario === "empty"
            ? []
            : [
                storedMcpTool,
                memberTool(),
                memberTool({
                  id: 9,
                  name: "Project calendar",
                  display_name: "Project calendar",
                  description: "Read project milestones and calendar events.",
                  oauth_config_id: 9,
                }),
              ]
        );
      if (path === "/api/user-oauth-token/status") {
        if (scenario === "account-loading")
          return new Promise<Response>(() => {});
        return jsonResponse(
          oauthConnected
            ? [{ oauth_config_id: 9, expires_at: null, is_expired: false }]
            : []
        );
      }
      if (path === "/api/mcp/user-credentials" && init?.method === "POST") {
        credentialsSaved = true;
        return jsonResponse({});
      }
      if (path === "/api/oauth-config/9/token" && init?.method === "DELETE") {
        oauthConnected = false;
        return jsonResponse({});
      }
      return jsonResponse(
        { detail: `No member Plugins story fixture for ${path}` },
        404
      );
    };
    window.fetch = mockFetch;
    setReady(true);
    return () => {
      if (window.fetch === mockFetch) window.fetch = originalFetch;
      window.open = originalOpen;
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
        <div className="h-screen bg-background-tint-01">
          <NextIntlClientProvider locale="en" messages={memberPluginMessages}>
            <MemberPluginsPage
              initialFilter={initialFilter}
              surface={surface}
            />
          </NextIntlClientProvider>
        </div>
      </UserProvider>
    </SWRConfig>
  ) : null;
}

const meta = {
  title: "Apps/Plugins/Member directory",
  component: MemberPluginsStory,
  parameters: { layout: "fullscreen" },
  args: { scenario: "ready" },
} satisfies Meta<typeof MemberPluginsStory>;
export default meta;
type Story = StoryObj<typeof meta>;

export const All: Story = {};
export const Craft: Story = { args: { surface: "craft" } };
export const CraftEmpty: Story = {
  args: { surface: "craft", scenario: "empty" },
};
export const NeedsSignIn: Story = { args: { initialFilter: "needsSignIn" } };
export const WorkspaceManager: Story = { args: { scenario: "manager" } };
export const EmptyWorkspace: Story = { args: { scenario: "empty" } };
export const PartialSourceError: Story = { args: { scenario: "source-error" } };
export const AccountStatusLoading: Story = {
  args: { scenario: "account-loading", initialFilter: "needsSignIn" },
};

export const StoredToolsDetail: Story = {
  play: async () => {
    const page = within(document.body);
    await userEvent.click(
      await page.findByRole("button", { name: "View Linear" })
    );
    const dialog = await page.findByRole("dialog", { name: /^Linear/ });
    await userEvent.click(within(dialog).getByRole("tab", { name: "Tools" }));
    await expect(within(dialog).getByText("Search issues")).toBeVisible();
    await expect(
      within(dialog).getByRole("button", { name: "Use in Chat" })
    ).toBeVisible();
  },
};

export const OAuthConnection: Story = {
  args: { initialFilter: "needsSignIn" },
  play: async () => {
    const page = within(document.body);
    await userEvent.click(
      await page.findByRole("button", { name: "Connect Notion" })
    );
    await expect(
      await page.findByRole("dialog", { name: /^Connect Notion/ })
    ).toBeVisible();
  },
};

export const CredentialEntry: Story = {
  args: { initialFilter: "needsSignIn" },
  play: async () => {
    const page = within(document.body);
    await userEvent.click(
      await page.findByRole("button", { name: "Connect Support desk" })
    );
    await userEvent.type(
      await page.findByLabelText("api_key"),
      "member-story-key"
    );
    await expect(page.getByRole("button", { name: "Connect" })).toBeEnabled();
  },
};

export const CredentialSuccess: Story = {
  args: { initialFilter: "needsSignIn" },
  play: async () => {
    const page = within(document.body);
    await userEvent.click(
      await page.findByRole("button", { name: "Connect Support desk" })
    );
    await userEvent.type(
      await page.findByLabelText("api_key"),
      "member-story-key"
    );
    await userEvent.click(page.getByRole("button", { name: "Connect" }));
    const dialog = await page.findByRole("dialog", { name: /^Support desk/ });
    await expect(within(dialog).getByText("Connected")).toBeVisible();
  },
};

export const SignInBlocked: Story = {
  args: { scenario: "popup-blocked", initialFilter: "needsSignIn" },
  play: async () => {
    const page = within(document.body);
    await userEvent.click(
      await page.findByRole("button", { name: "Connect Notion" })
    );
    await userEvent.click(
      page.getByRole("button", { name: "Continue to Notion" })
    );
    await expect(await page.findByRole("alert")).toHaveTextContent(
      "Allow popups and try again."
    );
  },
};

export const SharedOAuthDisconnect: Story = {
  play: async () => {
    const page = within(document.body);
    await userEvent.click(
      await page.findByRole("button", { name: "View Project calendar" })
    );
    await userEvent.click(
      page.getByRole("button", { name: "Disconnect account" })
    );
    await expect(
      page.getByText(
        /all plugins and apps that use the same OAuth configuration/
      )
    ).toBeVisible();
  },
};
