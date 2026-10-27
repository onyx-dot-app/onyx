import type React from "react";
import type { IconProps } from "@opal/types";
import type { ActionPolicy } from "@/app/craft/v1/apps/registry";
import type { PermissionsOf } from "@/lib/permissions/resource-actions";

export enum MCPServerStatus {
  CREATED = "CREATED",
  AWAITING_AUTH = "AWAITING_AUTH",
  FETCHING_TOOLS = "FETCHING_TOOLS",
  CONNECTED = "CONNECTED",
  DISCONNECTED = "DISCONNECTED",
}

export interface MCPServer {
  id: number;
  name: string;
  description?: string;
  server_url: string;
  owner: string;
  transport?: MCPTransportType;
  auth_type?: MCPAuthenticationType;
  auth_performer?: MCPAuthenticationPerformer;
  oauth_provider_mode?: MCPOAuthProviderMode;
  oauth_setup_mode?: "automatic" | "own_client" | null;
  oauth_cimd_enabled?: boolean;
  oauth_authorization_endpoint?: string;
  oauth_token_endpoint?: string;
  oauth_scopes_override?: string[];
  oauth_additional_auth_params?: Record<string, string>;
  // Null when there is no user context.
  connection_status: MCPConnectionStatus | null;
  // Whether Craft can produce auth headers for the user's sandbox sessions.
  // Only the Craft listing computes it.
  craft_connected?: boolean;
  auth_template?: MCPAuthTemplate | null;
  admin_credentials?: Record<string, string>;
  user_credentials?: Record<string, string>;
  status: MCPServerStatus;
  is_public: boolean;
  groups: number[];
  users: string[];
  available_in_craft?: boolean;
  default_chat_enabled?: boolean | null;
  user_enabled_in_chat?: boolean;
  user_enabled_in_craft?: boolean;
  // Sparse per-tool Craft approval overrides (unlisted tools default to ASK).
  // Present on owner/admin views only.
  action_policies?: Record<string, ActionPolicy> | null;
  users_can_manage_policies?: boolean;
  last_refreshed_at?: string;
  tool_count: number;
  // Server-stamped affordance map; fail-closed (absent = denied).
  permissions?: PermissionsOf<"MCPServer">;
}

export interface MCPAuthTemplate {
  headers: Record<string, string>;
  required_fields: string[];
}

export interface AgentEditorMCPServer extends MCPServer {
  can_attach: boolean;
}

export interface MCPServersResponse {
  assistant_id?: string | null;
  mcp_servers: MCPServer[];
}

export interface MCPUserPreferences {
  enabled_in_chat: boolean;
  enabled_in_craft: boolean;
}

export type MCPUserPreferencesRequest =
  | { enabled_in_chat: boolean; enabled_in_craft?: boolean }
  | { enabled_in_chat?: boolean; enabled_in_craft: boolean };

export interface MCPServerCreateRequest {
  available_in_craft?: boolean;
  name: string;
  description?: string;
  server_url: string;
  is_public: boolean;
  groups: number[];
  users: string[];
}

export interface MCPServerUpdateRequest {
  name?: string;
  description?: string;
  server_url?: string;
  // Omit to leave the server's existing access unchanged.
  is_public?: boolean;
  groups?: number[];
  users?: string[];
  available_in_craft?: boolean;
  // Full replace of the stored per-tool overrides; omit to leave unchanged.
  action_policies?: Record<string, ActionPolicy>;
  users_can_manage_policies?: boolean;
}

export interface MCPTool {
  id: string;
  name: string;
  description: string;
  icon?: React.FunctionComponent<IconProps>;
  isAvailable: boolean;
  isEnabled: boolean;
  permissions?: PermissionsOf<"Action">;
}

export enum MCPConnectionStatus {
  NOT_CONNECTED = "not_connected",
  CONNECTED = "connected",
  REAUTH_REQUIRED = "reauth_required",
}

export enum MCPAuthenticationType {
  NONE = "NONE",
  API_TOKEN = "API_TOKEN",
  OAUTH = "OAUTH",
  PT_OAUTH = "PT_OAUTH", // Pass-Through OAuth
}

export enum MCPAuthenticationPerformer {
  ADMIN = "ADMIN",
  PER_USER = "PER_USER",
}

export enum MCPOAuthProviderMode {
  AUTO_DISCOVERY = "AUTO_DISCOVERY",
  KNOWN_PROVIDER = "KNOWN_PROVIDER",
}

export enum MCPTransportType {
  STDIO = "STDIO",
  STREAMABLE_HTTP = "STREAMABLE_HTTP",
  SSE = "SSE",
}

/** The agent editor's form fields for one MCP server: its switch, then one per tool. */
export interface MCPServerFormValues {
  enabled: boolean;
  [tool: `tool_${string}`]: boolean;
}

/** The MCP slice of the agent editor's form, keyed by server field name. */
export type MCPServersFormValues = Record<
  `mcp_server_${number}`,
  MCPServerFormValues | undefined
>;

export type MCPAuthenticationServer = Pick<
  MCPServer,
  | "id"
  | "name"
  | "auth_type"
  | "auth_performer"
  | "auth_template"
  | "connection_status"
  | "user_credentials"
  | "transport"
>;
export interface MCPOAuthDiscovery {
  status: "metadata_found" | "metadata_missing" | "unreachable";
  supports_automatic_registration: boolean | null;
  authorization_endpoint: string | null;
  token_endpoint: string | null;
}

export type MCPSetupProbeResult =
  | {
      kind: "public";
      transport: MCPTransportType.STREAMABLE_HTTP | MCPTransportType.SSE;
      tool_count: number;
      server_name: string;
    }
  | {
      kind: "oauth";
      transport: MCPTransportType.STREAMABLE_HTTP | MCPTransportType.SSE | null;
      discovery: MCPOAuthDiscovery;
    }
  | {
      kind: "auth_unknown";
      transport: MCPTransportType.STREAMABLE_HTTP | MCPTransportType.SSE | null;
    }
  | { kind: "unreachable"; reason: "blocked" | "connection_failed" };

export type MCPSetupRecommendation = Exclude<
  MCPSetupProbeResult,
  { kind: "unreachable" }
>;

export interface MCPProbeProgress {
  type: "progress";
  stage: "contacting_server" | "authentication";
  state: "pending" | "success" | "error";
}

export interface MCPServerConfigurationValues extends MCPServerCreateRequest {
  access_mode: "public" | "groups";
}
