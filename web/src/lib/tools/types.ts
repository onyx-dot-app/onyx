import type React from "react";
import { MCPServer } from "@/lib/tools/interfaces";
import type { IconProps } from "@opal/types";

// Generic action status for UI components
export enum ActionStatus {
  CONNECTED = "connected",
  PENDING = "pending",
  DISCONNECTED = "disconnected",
  FETCHING = "fetching",
}

export enum MCPServerStatus {
  CREATED = "CREATED",
  AWAITING_AUTH = "AWAITING_AUTH",
  FETCHING_TOOLS = "FETCHING_TOOLS",
  CONNECTED = "CONNECTED",
  DISCONNECTED = "DISCONNECTED",
}

// Extended interface with status field
export interface MCPServerWithStatus
  extends Omit<MCPServer, "transport" | "auth_type" | "auth_performer"> {
  status: MCPServerStatus;
  transport: string | null;
  auth_type: string | null;
  auth_performer: string | null;
  tool_count: number;
}

export interface MCPServerCreateRequest {
  name: string;
  description?: string;
  server_url: string;
}

export interface MCPServerUpdateRequest {
  name?: string;
  description?: string;
  server_url?: string;
}

export interface MCPTool {
  id: string;
  name: string;
  description: string;
  icon?: React.FunctionComponent<IconProps>;
  isAvailable: boolean;
  isEnabled: boolean;
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

  // Whether the tool is enabled
  enabled: boolean;

  // Visibility settings from backend TOOL_VISIBILITY_CONFIG
  chat_selectable: boolean;
  agent_creation_selectable: boolean;
  default_enabled: boolean;
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

export interface ApiResponse<T> {
  data: T | null;
  error: string | null;
}

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
