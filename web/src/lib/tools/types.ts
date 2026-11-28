import type { ActionPolicy } from "@/app/craft/v1/apps/registry";
import type { PermissionsOf } from "@/lib/permissions/resource-actions";
import type {
  SearchFiltersRequest,
  TagSelection,
} from "@/lib/searchFilters/types";

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
  custom_headers: { key: string; value: string }[] | null;

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
  // The integration of an OpenAPI or MCP tool; chat tool options name it.
  // Only the tool list sets it.
  integration_id?: number | null;

  // Whether the tool is enabled
  enabled: boolean;

  // Visibility settings from backend TOOL_VISIBILITY_CONFIG
  chat_selectable: boolean;
  agent_creation_selectable: boolean;
  default_enabled: boolean;
  default_action_policy?: ActionPolicy | null;

  // Server-stamped affordance map; fail-closed (absent = denied).
  permissions?: PermissionsOf<"Action">;
}

export interface ApiResponse<T> {
  data: T | null;
  error: string | null;
}

/**
 * What a chat has been told to do about one tool.
 *
 * Neutral is the absence of a state rather than a third name for one, so a
 * tool nobody has said anything about is not recorded. A tool that appears
 * after the choice was made is therefore already neutral, with nothing having
 * to go and enrol it.
 */
export type ToolState = "preferred" | "disabled";

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
  tags: readonly TagSelection[];
  /** An ISO datetime string, kept serializable rather than as a `Date`. */
  timeRange: { from: string } | null;
}

/** A built-in tool by its id, or an integration with the action keys to
 * keep. */
export type ToolOptionsEntry =
  | { type: "capability"; tool_id: number }
  | { type: "integration"; integration_id: number; actions?: string[] | null };

/** A built-in tool, or one action of an integration. */
export type ToolPreference =
  | { type: "capability"; tool_id: number }
  | { type: "action"; integration_id: number; action: string };

/** A preferred integration action. The web keeps it but has no control for
 * it. */
export type ActionPreference = Extract<ToolPreference, { type: "action" }>;

/**
 * The tools, integrations and search filters of a chat. A send carries them, and
 * the server saves them on an existing chat: the chat-session detail returns
 * them, and the tool-options PATCH is their only writer. Turns the server
 * starts use them. `allowed` null means every tool and integration of the agent.
 */
export interface ChatToolOptions {
  allowed: ToolOptionsEntry[] | null;
  preferred: ToolPreference | null;
  internal_search_filters: SearchFiltersRequest | null;
}
