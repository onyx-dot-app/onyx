// Per-user, per-agent tool preferences — the same record web reads, so disabling a tool here
// disables it there too (intentional).
import { apiFetch } from "@/api/client";

export interface AgentPreference {
  disabled_tool_ids: number[];
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

// Replaces the row wholesale, and the field is required — always send the full array.
export function patchAgentPreferences(
  agentId: number,
  disabledToolIds: number[],
): Promise<void> {
  return apiFetch<void>(`/user/assistant/${agentId}/preferences`, {
    method: "PATCH",
    body: { disabled_tool_ids: disabledToolIds },
  });
}
