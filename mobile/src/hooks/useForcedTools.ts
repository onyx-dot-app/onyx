// Ephemeral "force this tool for the next turn" state. Web stores a number[] but only ever fills
// it with one id and sends forcedToolIds[0] (web/src/lib/hooks/useForcedTools.ts), so a single
// nullable id is the same thing without the dead cardinality.
import { useCallback, useEffect, useRef, useState } from "react";

interface UseForcedToolsArgs {
  chatSessionId: string | null;
  // undefined = unresolved (agents loading, or a new session missing from the sessions list).
  agentId: number | undefined;
  // null = not in a project. A project composer is a different conversation scope, so crossing
  // the boundary resets, matching web (web/src/views/AppPage.tsx:166-169).
  projectId: number | null;
}

export interface ForcedTools {
  forcedToolId: number | null;
  toggleForcedTool: (toolId: number) => void;
  clearForcedTool: () => void;
}

export function useForcedTools({
  chatSessionId,
  agentId,
  projectId,
}: UseForcedToolsArgs): ForcedTools {
  const [forcedToolId, setForcedToolId] = useState<number | null>(null);
  const previousChatSessionId = useRef<string | null>(chatSessionId);
  const previousAgentId = useRef<number | undefined>(agentId);
  const previousProjectId = useRef<number | null>(projectId);

  // Preserve across null→new-session: that transition *is* the send.
  useEffect(() => {
    const previousId = previousChatSessionId.current;
    previousChatSessionId.current = chatSessionId;
    if (previousId !== null && previousId !== chatSessionId) {
      setForcedToolId(null);
    }
  }, [chatSessionId]);

  // Only known→known counts as a switch; the unresolved step after a send must not clear the
  // force that send just used.
  useEffect(() => {
    if (agentId === undefined) return;
    const previousId = previousAgentId.current;
    previousAgentId.current = agentId;
    if (previousId !== undefined && previousId !== agentId) {
      setForcedToolId(null);
    }
  }, [agentId]);

  // Needs no such guard: the send that creates a chat has already read its options by the time
  // the route flips, so every project transition is a real scope change.
  useEffect(() => {
    const previousId = previousProjectId.current;
    previousProjectId.current = projectId;
    if (previousId !== projectId) setForcedToolId(null);
  }, [projectId]);

  const toggleForcedTool = useCallback((toolId: number) => {
    setForcedToolId((current) => (current === toolId ? null : toolId));
  }, []);

  const clearForcedTool = useCallback(() => setForcedToolId(null), []);

  return { forcedToolId, toggleForcedTool, clearForcedTool };
}
