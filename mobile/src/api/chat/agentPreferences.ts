// Per-user, per-agent tool preferences — the same record web reads, so disabling a tool here
// disables it there too (intentional).
import { apiFetch } from "@/api/client";

export interface AgentPreference {
  // Built-in tools switched off.
  disabled_tool_ids: number[];
  // Plugins switched off; an OpenAPI or MCP tool is on or off through its plugins.
  disabled_plugin_ids?: string[];
}

// Backend types this `dict[int, ...]`, but JSON keys are strings: index with `String(agentId)`.
export type AgentPreferences = Record<string, AgentPreference>;

export function getAgentPreferences(
  signal?: AbortSignal,
): Promise<AgentPreferences | null> {
  return apiFetch<AgentPreferences | null>("/user/assistant/preferences", {
    signal,
  });
}

// Replaces both lists, so always send the full arrays.
export function patchAgentPreferences(
  agentId: number,
  disabledToolIds: number[],
  disabledPluginIds: string[],
): Promise<void> {
  return apiFetch<void>(`/user/assistant/${agentId}/preferences`, {
    method: "PATCH",
    body: {
      disabled_tool_ids: disabledToolIds,
      disabled_plugin_ids: disabledPluginIds,
    },
  });
}
