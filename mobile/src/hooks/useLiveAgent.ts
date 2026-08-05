import { useCallback } from "react";
import { router } from "expo-router";

import { useAgents, usePinnedAgents } from "@/api/chat/agents";
import { useWorkspaceSettings } from "@/api/settings";
import { MinimalAgent, resolveLiveAgent } from "@/chat/agents";

export function useLiveAgent(
  selectedAgentId: number | null,
  sessionPersonaId: number | null,
): MinimalAgent | null {
  const { agents } = useAgents();
  const { pinnedAgents } = usePinnedAgents();
  const { settings } = useWorkspaceSettings();

  return resolveLiveAgent({
    agents,
    pinnedAgents,
    disableDefaultAssistant: settings.disable_default_assistant,
    selectedAgentId,
    sessionPersonaId,
  });
}

// Pick an agent: auto-pin it (rail grows) + open a new-chat landing with it selected.
export function useSelectAgent() {
  const { ensurePinned } = usePinnedAgents();

  return useCallback(
    (agent: MinimalAgent, onBeforeNavigate?: () => void) => {
      void ensurePinned(agent);
      onBeforeNavigate?.();
      router.navigate({ pathname: "/", params: { agentId: String(agent.id) } });
    },
    [ensurePinned],
  );
}
