import type React from "react";
import type { IconProps } from "@opal/types";
import type { EndpointPolicy } from "@/app/craft/v1/apps/registry";
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
  oauth_authorization_endpoint?: string;
  oauth_token_endpoint?: string;
  oauth_scopes_override?: string[];
  oauth_additional_auth_params?: Record<string, string>;
  // Whether this user's credentials resolve for the server right now (or the
  // server needs no per-user auth). Absent when there is no user context.
  user_can_authenticate?: boolean;
  // Whether Craft will actually emit this server into the user's sessions, i.e.
  // whether the sandbox proxy can authenticate them against it. Unlike the flag
  // above it asks whether stored credentials yield auth headers, not whether a
  // config row exists. Only the Craft listing computes it.
  craft_connected?: boolean;
  auth_template?: MCPAuthTemplate | null;
  admin_credentials?: Record<string, string>;
  user_credentials?: Record<string, string>;
  status: MCPServerStatus;
  is_public: boolean;
  groups: number[];
  users: string[];
  available_in_craft?: boolean;
  // Sparse per-tool Craft approval overrides (unlisted tools default to ASK).
  // Present on owner/admin views only.
  tool_policies?: Record<string, EndpointPolicy> | null;
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

export interface MCPServerCreateRequest {
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
  tool_policies?: Record<string, EndpointPolicy>;
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
