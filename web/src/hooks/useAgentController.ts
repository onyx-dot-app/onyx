"use client";

import { MinimalPersonaSnapshot } from "@/app/admin/agents/interfaces";
import { useCallback, useMemo, useState } from "react";
import { ChatSession } from "@/app/app/interfaces";
import { useAgents, usePinnedAgents } from "@/hooks/useAgents";
import { useSearchParams } from "next/navigation";
import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";
import { useSettingsContext } from "@/providers/SettingsProvider";

export default function useAgentController({
  selectedChatSession,
  onAgentSelect,
}: {
  selectedChatSession: ChatSession | null | undefined;
  onAgentSelect?: () => void;
}) {
  const searchParams = useSearchParams();
  const { agents: availableAgents } = useAgents();
  const { pinnedAgents: pinnedAgents } = usePinnedAgents();
  const combinedSettings = useSettingsContext();

  const defaultAgentIdRaw = searchParams?.get(SEARCH_PARAM_NAMES.PERSONA_ID);
  const defaultAgentId = defaultAgentIdRaw
    ? parseInt(defaultAgentIdRaw)
    : undefined;

  const existingChatSessionAgentId = selectedChatSession?.persona_id;
  const [selectedAgent, setSelectedAssistant] = useState<
    MinimalPersonaSnapshot | undefined
  >(
    // NOTE: look through available assistants here, so that even if the user
    // has hidden this agent it still shows the correct assistant when
    // going back to an old chat session
    existingChatSessionAgentId !== undefined
      ? availableAgents.find(
          (assistant) => assistant.id === existingChatSessionAgentId
        )
      : defaultAgentId !== undefined
        ? availableAgents.find((assistant) => assistant.id === defaultAgentId)
        : undefined
  );

  // Current assistant is decided based on this ordering
  // 1. Alternative assistant (assistant selected explicitly by user)
  // 2. Selected assistant (assistant default in this chat session)
  // 3. Unified assistant (ID 0) if available (unless disabled)
  // 4. First pinned assistants (ordered list of pinned assistants)
  // 5. Available assistants (ordered list of available assistants)
  // Relevant test: `live_assistant.spec.ts`
  const liveAgent: MinimalPersonaSnapshot | undefined = useMemo(() => {
    if (selectedAgent) return selectedAgent;

    const disableDefaultAssistant =
      combinedSettings?.settings?.disable_default_assistant ?? false;

    if (disableDefaultAssistant) {
      // Skip unified assistant (ID 0), go straight to pinned/available
      // Filter out ID 0 from both pinned and available assistants
      const nonDefaultPinned = pinnedAgents.filter((a) => a.id !== 0);
      const nonDefaultAvailable = availableAgents.filter((a) => a.id !== 0);

      return (
        nonDefaultPinned[0] || nonDefaultAvailable[0] || availableAgents[0] // Last resort fallback
      );
    }

    // Try to use the unified assistant (ID 0) as default
    const unifiedAgent = availableAgents.find((a) => a.id === 0);
    if (unifiedAgent) return unifiedAgent;

    // Fall back to pinned or available assistants
    return pinnedAgents[0] || availableAgents[0];
  }, [selectedAgent, pinnedAgents, availableAgents, combinedSettings]);

  const setSelectedAgentFromId = useCallback(
    (agentId: number | null | undefined) => {
      // NOTE: also intentionally look through available assistants here, so that
      // even if the user has hidden an agent they can still go back to it
      // for old chats
      let newAssistant =
        agentId !== null
          ? availableAgents.find((assistant) => assistant.id === agentId)
          : undefined;

      // if no assistant was passed in / found, use the default agent
      if (!newAssistant && defaultAgentId !== undefined) {
        newAssistant = availableAgents.find(
          (assistant) => assistant.id === defaultAgentId
        );
      }

      setSelectedAssistant(newAssistant);
      onAgentSelect?.();
    },
    [availableAgents, defaultAgentId, onAgentSelect]
  );

  return {
    // main assistant selection
    selectedAgent,
    setSelectedAgentFromId,

    // final computed assistant
    liveAgent,
  };
}
