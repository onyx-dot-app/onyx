import type {
  ExternalAppType,
  ExternalAppUserResponse,
} from "@/app/craft/v1/apps/registry";
import type { BuiltinSkill, CustomSkill } from "@/lib/skills/types";
import {
  MCPConnectionStatus,
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
  MCPServerStatus,
  type MCPServer,
} from "@/lib/mcp/types";

export function builtinFixture(over: Partial<BuiltinSkill> = {}): BuiltinSkill {
  return {
    source: "builtin",
    id: "builtin-1",
    name: "pptx",
    description: "Build PowerPoint decks.",
    is_available: true,
    unavailable_reason: null,
    is_valid: true,
    is_personal: false,
    enabled: true,
    can_toggle: false,
    installation_policy: "AVAILABLE",
    default_installation_policy: "AVAILABLE",
    can_delete: true,
    required_for_user: false,
    author_user_id: null,
    author_email: null,
    owner: null,
    ownership_vacant: false,
    created_at: null,
    updated_at: null,
    user_shares: [],
    group_shares: [],
    group_summaries: [],
    public_permission: null,
    user_permission: "VIEWER",
    external_app: null,
    current_version_id: null,
    current_version_number: null,
    published_version_number: null,
    pending_version_number: null,
    ...over,
  };
}

export function customFixture(over: Partial<CustomSkill> = {}): CustomSkill {
  return {
    source: "custom",
    id: "custom-1",
    name: "report-writer",
    description: "Draft a structured report from notes.",
    is_available: null,
    unavailable_reason: null,
    is_valid: true,
    is_personal: false,
    enabled: true,
    can_toggle: true,
    installation_policy: "AVAILABLE",
    default_installation_policy: "AVAILABLE",
    can_delete: true,
    required_for_user: false,
    author_user_id: null,
    author_email: null,
    owner: null,
    ownership_vacant: true,
    created_at: null,
    updated_at: null,
    user_shares: [],
    group_shares: [],
    group_summaries: [],
    public_permission: "VIEWER",
    user_permission: "VIEWER",
    external_app: null,
    current_version_id: null,
    current_version_number: null,
    published_version_number: null,
    pending_version_number: null,
    ...over,
  };
}

export function appFixture(
  over: Partial<ExternalAppUserResponse> & {
    app_type: ExternalAppType;
    id: number;
  }
): ExternalAppUserResponse {
  return {
    name: `App ${over.id}`,
    credential_keys: ["token"],
    credential_values: over.authenticated === false ? {} : { token: "***" },
    authenticated: true,
    supports_oauth: false,
    ...over,
  };
}

export function mcpServerFixture(
  over: Partial<MCPServer> & { id: number }
): MCPServer {
  return {
    name: `MCP ${over.id}`,
    description: "An MCP server",
    server_url: `https://mcp-${over.id}.example.com/mcp`,
    owner: "admin@example.com",
    auth_type: MCPAuthenticationType.API_TOKEN,
    auth_performer: MCPAuthenticationPerformer.PER_USER,
    connection_status: MCPConnectionStatus.CONNECTED,
    craft_connected: true,
    status: MCPServerStatus.CONNECTED,
    is_public: true,
    groups: [],
    users: [],
    available_in_craft: true,
    tool_count: 2,
    ...over,
  };
}
