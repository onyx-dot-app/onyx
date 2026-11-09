import { useCallback, useEffect, useRef, useState } from "react";

interface UsePreferredToolsArgs {
  chatSessionId: string | null;
  // undefined = unresolved (agents loading, or a new session missing from the sessions list).
  agentId: number | undefined;
  projectId: number | null;
}

export interface PreferredTools {
  preferredToolId: number | null;
  togglePreferredTool: (toolId: number) => void;
  /*
   * Unconditional: the source coupling pins search on every source change, where a toggle would
   * release an already-pinned one.
   */
  preferTool: (toolId: number) => void;
  clearPreferredTool: () => void;
}

export function usePreferredTools({
  chatSessionId,
  agentId,
  projectId,
}: UsePreferredToolsArgs): PreferredTools {
  const [preferredToolId, setPreferredToolId] = useState<number | null>(null);
  const previousChatSessionId = useRef<string | null>(chatSessionId);
  const previousAgentId = useRef<number | undefined>(agentId);
  const previousProjectId = useRef<number | null>(projectId);

  // Preserve across null→new-session: that transition *is* the send.
  useEffect(() => {
    const previousId = previousChatSessionId.current;
    previousChatSessionId.current = chatSessionId;
    if (previousId !== null && previousId !== chatSessionId) {
      setPreferredToolId(null);
    }
  }, [chatSessionId]);

  /*
   * Only known→known counts as a switch; the unresolved step after a send must not clear the
   * preference that send just used.
   */
  useEffect(() => {
    if (agentId === undefined) return;
    const previousId = previousAgentId.current;
    previousAgentId.current = agentId;
    if (previousId !== undefined && previousId !== agentId) {
      setPreferredToolId(null);
    }
  }, [agentId]);

  /*
   * No such guard needed: the send reads its options before the route flips, so every project
   * transition is a real scope change.
   */
  useEffect(() => {
    const previousId = previousProjectId.current;
    previousProjectId.current = projectId;
    if (previousId !== projectId) setPreferredToolId(null);
  }, [projectId]);

  const togglePreferredTool = useCallback((toolId: number) => {
    setPreferredToolId((current) => (current === toolId ? null : toolId));
  }, []);

  const preferTool = useCallback((toolId: number) => {
    setPreferredToolId(toolId);
  }, []);

  const clearPreferredTool = useCallback(() => setPreferredToolId(null), []);

  return {
    preferredToolId,
    togglePreferredTool,
    preferTool,
    clearPreferredTool,
  };
}
