import { MCPConnectionStatus } from "@/lib/mcp/types";
import { useEffect, useLayoutEffect, useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within } from "storybook/test";
import { SWRConfig, type State } from "swr";
import type { MinimalAgent } from "@/lib/agents/types";
import { MCPAuthenticationType } from "@/lib/mcp/types";
import { useToolConfiguration } from "@/lib/tools/hooks";
import { UserProvider } from "@/providers/UserProvider";
import ChatPluginsPopover from "@/sections/plugins/ChatPluginsPopover";
import {
  jsonResponse,
  memberServer,
  memberTool,
  storedMcpTool,
} from "@/sections/plugins/__tests__/memberPluginFixtures";

type Scenario = "ready" | "disabled" | "forced" | "empty" | "loading" | "error";
interface ChatPluginsStoryProps {
  scenario: Scenario;
}

const tools = [
  storedMcpTool,
  memberTool({ id: 72, mcp_server_id: 7, definition: null, name: "get_issue" }),
  memberTool({
    id: 81,
    mcp_server_id: 8,
    definition: null,
    name: "get_ticket",
  }),
  memberTool(),
];
const agent: MinimalAgent = {
  id: 5,
  name: "Support agent",
  description: "Resolve support tickets",
  tools,
  starter_messages: null,
  document_sets: [],
  is_public: true,
  is_listed: true,
  display_priority: null,
  is_featured: false,
  builtin_persona: false,
  owner: null,
  owner_group: null,
  user_permission: "VIEWER",
};

function StoryComposer({ scenario }: ChatPluginsStoryProps) {
  const configuration = useToolConfiguration(agent.id);
  const { ready, setToolState } = configuration;
  useEffect(() => {
    if (!ready) return;
    if (scenario === "disabled") {
      setToolState(71, () => "disabled");
      setToolState(72, () => "disabled");
    }
    if (scenario === "forced") setToolState(71, () => "forced");
  }, [ready, setToolState, scenario]);
  return (
    <div className="flex min-h-96 w-full items-start justify-center bg-background-neutral-01 p-8">
      <ChatPluginsPopover
        agent={scenario === "empty" ? { ...agent, tools: [] } : agent}
        toolConfiguration={configuration}
      />
    </div>
  );
}

function ChatPluginsStory({ scenario }: ChatPluginsStoryProps) {
  const [ready, setReady] = useState(false);
  const [cache] = useState(() => new Map<string, State>());
  useLayoutEffect(() => {
    const original = window.fetch;
    let connected = false;
    const fixture: typeof fetch = async (input, init) => {
      const path = new URL(
        input instanceof Request ? input.url : String(input),
        window.location.origin
      ).pathname;
      if (!path.startsWith("/api/")) return original(input, init);
      if (path === "/api/me")
        return jsonResponse({
          id: "chat-plugin-member",
          email: "member@example.com",
          is_active: true,
          is_superuser: false,
          is_verified: true,
          account_type: "basic",
          preferences: {},
          team_name: null,
          effective_permissions: [],
          admin_capabilities: [],
        });
      if (path === "/api/settings")
        return jsonResponse({ tier: "community", ee_features_enabled: false });
      if (path === "/api/auth/type")
        return jsonResponse({ auth_type: "basic", oauth_enabled: true });
      if (path === "/api/persona") return jsonResponse([agent]);
      if (path === "/api/chat/get-user-chat-sessions")
        return jsonResponse({ sessions: [], has_more: false });
      if (
        path === "/api/user/projects" ||
        path === "/api/manage/connector-status"
      )
        return jsonResponse([]);
      if (
        path === "/api/mcp/servers" ||
        path === "/api/mcp/servers/persona/5"
      ) {
        if (scenario === "loading") return new Promise<Response>(() => {});
        if (scenario === "error")
          return jsonResponse({ detail: "MCP unavailable" }, 503);
        return jsonResponse({
          mcp_servers:
            scenario === "empty"
              ? []
              : [
                  memberServer(),
                  memberServer({
                    id: 8,
                    name: "Support desk",
                    server_url: "https://support.example.com/mcp",
                    auth_type: MCPAuthenticationType.API_TOKEN,
                    connection_status: connected
                      ? MCPConnectionStatus.CONNECTED
                      : MCPConnectionStatus.NOT_CONNECTED,
                  }),
                ],
        });
      }
      if (path === "/api/tool")
        return jsonResponse(scenario === "empty" ? [] : tools);
      if (path === "/api/user-oauth-token/status") return jsonResponse([]);
      if (path === "/api/mcp/user-credentials") {
        connected = true;
        return jsonResponse({});
      }
      return jsonResponse(
        { detail: `No chat plugin story fixture for ${path}` },
        404
      );
    };
    window.fetch = fixture;
    setReady(true);
    return () => {
      if (window.fetch === fixture) window.fetch = original;
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
        <StoryComposer scenario={scenario} />
      </UserProvider>
    </SWRConfig>
  ) : null;
}

const meta = {
  title: "Apps/Plugins/Chat picker",
  component: ChatPluginsStory,
  parameters: { layout: "fullscreen" },
  args: { scenario: "ready" },
  play: async () => {
    const page = within(document.body);
    await userEvent.click(await page.findByRole("button", { name: "Plugins" }));
  },
} satisfies Meta<typeof ChatPluginsStory>;
export default meta;
type Story = StoryObj<typeof meta>;

export const AttachedPlugins: Story = {};
export const DisabledGroup: Story = {
  args: { scenario: "disabled" },
  play: async () => {
    const page = within(document.body);
    await userEvent.click(await page.findByRole("button", { name: "Plugins" }));
    await expect(
      await page.findByRole("switch", { name: "Use Linear in this chat" })
    ).not.toBeChecked();
  },
};
export const ForcedTool: Story = { args: { scenario: "forced" } };
export const EmptyAgent: Story = { args: { scenario: "empty" } };
export const Loading: Story = { args: { scenario: "loading" } };
export const PartialFailure: Story = { args: { scenario: "error" } };
export const ConnectCredentials: Story = {
  play: async () => {
    const page = within(document.body);
    await userEvent.click(await page.findByRole("button", { name: "Plugins" }));
    await userEvent.click(await page.findByRole("button", { name: "Connect" }));
    await expect(await page.findByRole("dialog")).toBeVisible();
  },
};
