import { MCPConnectionStatus } from "@/lib/mcp/types";
import {
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
  MCPServerStatus,
  type MCPServer,
} from "@/lib/mcp/types";
import type { ToolSnapshot } from "@/lib/tools/types";
import type { ExternalAppUserResponse } from "@/app/craft/v1/apps/registry";
import englishMessages from "@/i18n/messages/en.json";

export const memberPluginMessages = {
  ...englishMessages,
  actions: {
    ...englishMessages.actions,
    memberPlugins: {
      ...englishMessages.actions.memberPlugins,
      filters: {
        label: "Connection status",
        all: "All",
        connected: "Connected",
        needsSignIn: "Needs sign-in",
        showAll: "Show all plugins",
      },
      kind: {
        ...englishMessages.actions.memberPlugins.kind,
        "external-app": "Craft App",
      },
      externalApp: {
        description: "Use your account in Craft.",
        craftOnly: "Craft only",
        craftOnlyDescription:
          "This app is available in Craft. Main Chat does not support it.",
      },
      detail: {
        ...englishMessages.actions.memberPlugins.detail,
        openInCraft: "Open in Craft",
      },
      state: {
        ...englishMessages.actions.memberPlugins.state,
        appsError: "Craft apps could not load.",
        appsLoading: "Loading Craft apps",
        emptyTitle: "No plugins found",
        emptyDescription:
          "Try another connection filter or ask your workspace admin to add a plugin.",
      },
    },
  },
};

export function memberApp(
  overrides: Partial<ExternalAppUserResponse> = {}
): ExternalAppUserResponse {
  return {
    id: 7,
    name: "Workspace GitHub",
    app_type: "GITHUB",
    credential_keys: [],
    credential_values: {},
    authenticated: false,
    supports_oauth: true,
    ...overrides,
  };
}

export function memberServer(overrides: Partial<MCPServer> = {}): MCPServer {
  return {
    id: 7,
    name: "Linear",
    description: "Issues and projects from your workspace.",
    server_url: "https://mcp.linear.app/mcp",
    owner: "admin@example.com",
    status: MCPServerStatus.CONNECTED,
    is_public: true,
    groups: [],
    users: [],
    tool_count: 1,
    available_in_craft: true,
    default_chat_enabled: true,
    connection_status: MCPConnectionStatus.CONNECTED,
    auth_type: MCPAuthenticationType.OAUTH,
    auth_performer: MCPAuthenticationPerformer.PER_USER,
    permissions: {},
    ...overrides,
  };
}

export function memberTool(
  overrides: Partial<ToolSnapshot> = {}
): ToolSnapshot {
  return {
    id: 7,
    name: "Reports API",
    display_name: "Reports API",
    description: "Read weekly reports and project summaries.",
    definition: {},
    custom_headers: [],
    in_code_tool_id: null,
    passthrough_auth: false,
    enabled: true,
    chat_selectable: true,
    agent_creation_selectable: true,
    default_enabled: false,
    default_chat_enabled: true,
    permissions: {},
    ...overrides,
  };
}

export const storedMcpTool = memberTool({
  id: 71,
  name: "search_issues",
  display_name: "Search issues",
  description: "Find issues in the projects you can access.",
  definition: null,
  mcp_server_id: 7,
});

export function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
