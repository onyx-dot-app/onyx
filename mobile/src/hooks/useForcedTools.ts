// Web stores a `number[]` but only ever holds one id, so a nullable id is the same thing.
import { useCallback, useEffect, useRef, useState } from "react";

interface UseForcedToolsArgs {
  chatSessionId: string | null;
  // undefined = unresolved (agents loading, or a new session missing from the sessions list).
  agentId: number | undefined;
  projectId: number | null;
}

export interface ForcedTools {
  forcedToolId: number | null;
  toggleForcedTool: (toolId: number) => void;
  /*
   * Unconditional: the source coupling pins search on every source change, where a toggle would
   * release an already-pinned one.
   */
  forceTool: (toolId: number) => void;
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

  /*
   * Only known→known counts as a switch; the unresolved step after a send must not clear the
   * force that send just used.
   */
  useEffect(() => {
    if (agentId === undefined) return;
    const previousId = previousAgentId.current;
    previousAgentId.current = agentId;
    if (previousId !== undefined && previousId !== agentId) {
      setForcedToolId(null);
    }
  }, [agentId]);

  /*
   * No such guard needed: the send reads its options before the route flips, so every project
   * transition is a real scope change.
   */
  useEffect(() => {
    const previousId = previousProjectId.current;
    previousProjectId.current = projectId;
    if (previousId !== projectId) setForcedToolId(null);
  }, [projectId]);

  const toggleForcedTool = useCallback((toolId: number) => {
    setForcedToolId((current) => (current === toolId ? null : toolId));
  }, []);

  const forceTool = useCallback((toolId: number) => {
    setForcedToolId(toolId);
  }, []);

  const clearForcedTool = useCallback(() => setForcedToolId(null), []);

  return { forcedToolId, toggleForcedTool, forceTool, clearForcedTool };
}
