"use client";

import { useState, useCallback } from "react";
import type { ToolConfigurationHandle } from "@/lib/tools/hooks";
import { useIncognito } from "@/providers/IncognitoProvider";

interface UseDeepResearchToggleProps {
  chatSessionId: string | null;
  agentId: number | undefined;
  toolConfiguration: Pick<
    ToolConfigurationHandle,
    "preferredToolId" | "clearPreferredTool"
  >;
}

/**
 * Custom hook for managing the agent search (deep research) toggle state.
 * Automatically resets the toggle to false when:
 * - Switching between existing chat sessions
 * - The assistant changes
 * - The page is reloaded (since state initializes to false)
 *
 * The toggle is preserved when transitioning from no chat session to a new session.
 *
 * @param chatSessionId - The current chat session ID
 * @param agentId - The current agent ID
 * @returns An object containing the toggle state and toggle function
 */
export default function useDeepResearchToggle({
  chatSessionId,
  agentId,
  toolConfiguration,
}: UseDeepResearchToggleProps) {
  const [deepResearchEnabled, setDeepResearchEnabled] = useState(false);
  const { incognitoEnabled } = useIncognito();
  const { preferredToolId } = toolConfiguration;

  // Reset when switching between existing chat sessions (not from null to a
  // new session), when the agent changes, or when a preferred tool is picked.
  const [synced, setSynced] = useState({
    chatSessionId,
    agentId,
    preferredToolId,
  });
  if (
    synced.chatSessionId !== chatSessionId ||
    synced.agentId !== agentId ||
    synced.preferredToolId !== preferredToolId
  ) {
    setSynced({ chatSessionId, agentId, preferredToolId });
    const switchedSession =
      synced.chatSessionId !== null && synced.chatSessionId !== chatSessionId;
    const pickedTool =
      synced.preferredToolId !== preferredToolId && preferredToolId !== null;
    if (switchedSession || synced.agentId !== agentId || pickedTool) {
      setDeepResearchEnabled(false);
    }
  }

  const toggleDeepResearch = useCallback(() => {
    if (!deepResearchEnabled) toolConfiguration.clearPreferredTool();
    setDeepResearchEnabled(!deepResearchEnabled);
  }, [deepResearchEnabled, toolConfiguration]);

  return {
    // Incognito chats run no child agents, so incognito masks the selection.
    deepResearchEnabled: deepResearchEnabled && !incognitoEnabled,
    toggleDeepResearch,
  };
}
