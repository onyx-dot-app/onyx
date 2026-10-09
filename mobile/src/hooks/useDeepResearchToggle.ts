// Ported from web/src/hooks/useDeepResearchToggle.ts.
import { useCallback, useEffect, useRef, useState } from "react";

interface UseDeepResearchToggleArgs {
  chatSessionId: string | null;
  // undefined = unresolved (agents loading, or a new session missing from the sessions list).
  agentId: number | undefined;
}

export interface DeepResearchToggle {
  deepResearchEnabled: boolean;
  toggleDeepResearch: () => void;
}

export function useDeepResearchToggle({
  chatSessionId,
  agentId,
}: UseDeepResearchToggleArgs): DeepResearchToggle {
  const [deepResearchEnabled, setDeepResearchEnabled] = useState(false);
  const previousChatSessionId = useRef<string | null>(chatSessionId);
  const previousAgentId = useRef<number | undefined>(agentId);

  // Preserve across null→new-session: that transition *is* the send, so resetting on every
  // `chatSessionId` change would clear the flag mid-send.
  useEffect(() => {
    const previousId = previousChatSessionId.current;
    previousChatSessionId.current = chatSessionId;
    if (previousId !== null && previousId !== chatSessionId) {
      setDeepResearchEnabled(false);
    }
  }, [chatSessionId]);

  // Only known→known counts as a switch. Web resets on every `agentId` change; on mobile that
  // would include the unresolved step after a send, clearing the flag that send just used.
  useEffect(() => {
    if (agentId === undefined) return;
    const previousId = previousAgentId.current;
    previousAgentId.current = agentId;
    if (previousId !== undefined && previousId !== agentId) {
      setDeepResearchEnabled(false);
    }
  }, [agentId]);

  const toggleDeepResearch = useCallback(
    () => setDeepResearchEnabled((enabled) => !enabled),
    [],
  );

  return { deepResearchEnabled, toggleDeepResearch };
}
