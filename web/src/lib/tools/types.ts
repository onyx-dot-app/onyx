import type { Tag } from "@/lib/types";
import type { PermissionsOf } from "@/lib/permissions/resource-actions";

// Generic action status for UI components
export enum ActionStatus {
  CONNECTED = "connected",
  PENDING = "pending",
  DISCONNECTED = "disconnected",
  FETCHING = "fetching",
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

  // Server-stamped affordance map; fail-closed (absent = denied).
  permissions?: PermissionsOf<"Action">;
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

/** Which drill-down the actions popover is showing, if any. */
export type SecondaryViewState =
  | { type: "sources" }
  | { type: "mcp"; serverId: number };

/**
 * What a chat has been told to do about one tool.
 *
 * Neutral is the absence of a state rather than a third name for one, so a
 * tool nobody has said anything about is not recorded. A tool that appears
 * after the choice was made is therefore already neutral, with nothing having
 * to go and enrol it.
 */
export type ToolState = "forced" | "disabled";

/**
 * The search-filter selection this chat sends with, in its stored form.
 *
 * Sources are a positive selection with an untouched sentinel: `null` means
 * the user never edited them, so every source is on. That is the default a
 * new chat starts from, and it keeps the storage invariant that a
 * configuration saying nothing is not stored. An array is an explicit
 * choice — including `[]`, which selects nothing.
 */
export interface ChatSearchFilters {
  /** `uniqueKey`s of the sources switched on; `null` means untouched (all on). */
  selectedSources: readonly string[] | null;
  documentSets: readonly string[];
  tags: readonly Tag[];
  /** ISO datetime strings, kept serializable rather than as `Date`s. */
  timeRange: { from: string; to: string } | null;
}
