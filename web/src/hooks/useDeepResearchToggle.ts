"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import type { ToolConfigurationHandle } from "@/lib/tools/hooks";

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
  const previousChatSessionId = useRef<string | null>(chatSessionId);

  // Reset when switching chat sessions, but preserve when going from null to a new session
  useEffect(() => {
    const previousId = previousChatSessionId.current;
    previousChatSessionId.current = chatSessionId;

    // Only reset if we're switching between actual sessions (not from null to a new session)
    if (previousId !== null && previousId !== chatSessionId) {
      setDeepResearchEnabled(false);
    }
  }, [chatSessionId]);

  // Reset when switching assistants
  useEffect(() => {
    setDeepResearchEnabled(false);
  }, [agentId]);

  useEffect(() => {
    if (toolConfiguration.preferredToolId !== null)
      setDeepResearchEnabled(false);
  }, [toolConfiguration.preferredToolId]);

  const toggleDeepResearch = useCallback(() => {
    if (!deepResearchEnabled) toolConfiguration.clearPreferredTool();
    setDeepResearchEnabled(!deepResearchEnabled);
  }, [deepResearchEnabled, toolConfiguration]);

  return {
    deepResearchEnabled,
    toggleDeepResearch,
  };
}
