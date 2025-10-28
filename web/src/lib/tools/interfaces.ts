export enum MCPAuthenticationType {
  NONE = "NONE",
  API_TOKEN = "API_TOKEN",
  OAUTH = "OAUTH",
}

export enum MCPAuthenticationPerformer {
  ADMIN = "ADMIN",
  PER_USER = "PER_USER",
}

export enum MCPTransportType {
  STDIO = "STDIO",
  STREAMABLE_HTTP = "STREAMABLE_HTTP",
  SSE = "SSE",
}
export interface ToolSnapshot {
  id: number;
  name: string;
  display_name: string;
  description: string;

  // only specified for Custom Tools. OpenAPI schema which represents
  // the tool's API.
  definition: Record<string, any> | null;

  // only specified for Custom Tools. Custom headers to add to the tool's API requests.
  custom_headers: { key: string; value: string }[];

  // only specified for Custom Tools. ID of the tool in the codebase.
  in_code_tool_id: string | null;

  // whether to pass through the user's OAuth token as Authorization header
  passthrough_auth: boolean;

  // OAuth configuration for this tool
  oauth_config_id?: number | null;
  oauth_config_name?: string | null;

  // If this is an MCP tool, which server it belongs to
  mcp_server_id?: number | null;
  user_id?: string | null;
}

export interface MCPServer {
  id: number;
  name: string;
  description?: string | null;
  server_url: string;
  owner: string;
  transport: MCPTransportType;
  auth_type: MCPAuthenticationType;
  auth_performer: MCPAuthenticationPerformer;
  is_authenticated: boolean;
  user_authenticated?: boolean | null;
}

export interface MCPServersResponse {
  assistant_id: string;
  mcp_servers: MCPServer[];
}

export interface MethodSpec {
  /* Defines a single method that is part of a custom tool. Each method maps to a single
  action that the LLM can choose to take. */
  name: string;
  summary: string;
  path: string;
  method: string;
  spec: Record<string, any>;
  custom_headers: { key: string; value: string }[];
}

// OAuth Configuration Types
export interface OAuthConfig {
  id: number;
  name: string;
  authorization_url: string;
  token_url: string;
  scopes: string[] | null;
  has_client_credentials: boolean;
  tool_count: number;
  created_at: string;
  updated_at: string;
}

export interface OAuthConfigCreate {
  name: string;
  authorization_url: string;
  token_url: string;
  client_id: string;
  client_secret: string;
  scopes?: string[];
  additional_params?: Record<string, any>;
}

export interface OAuthConfigUpdate {
  name?: string;
  authorization_url?: string;
  token_url?: string;
  client_id?: string;
  client_secret?: string;
  scopes?: string[];
  additional_params?: Record<string, any>;
}

export interface OAuthTokenStatus {
  oauth_config_id: number;
  expires_at: number | null;
  is_expired: boolean;
}
