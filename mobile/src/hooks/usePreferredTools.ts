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
  const [preference, setPreference] = useState<{ toolId: number } | null>(null);
  const preferredToolId = preference?.toolId ?? null;
  const previousChatSessionId = useRef<string | null>(chatSessionId);
  const previousAgentId = useRef<number | undefined>(agentId);
  const previousProjectId = useRef<number | null>(projectId);

  // Preserve across null→new-session: that transition *is* the send.
  useEffect(() => {
    const previousId = previousChatSessionId.current;
    previousChatSessionId.current = chatSessionId;
    if (previousId !== null && previousId !== chatSessionId) {
      setPreference(null);
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
      setPreference(null);
    }
  }, [agentId]);

  /*
   * No such guard needed: the send reads its options before the route flips, so every project
   * transition is a real scope change.
   */
  useEffect(() => {
    const previousId = previousProjectId.current;
    previousProjectId.current = projectId;
    if (previousId !== projectId) setPreference(null);
  }, [projectId]);

  const togglePreferredTool = useCallback((toolId: number) => {
    setPreference((current) =>
      current?.toolId === toolId ? null : { toolId },
    );
  }, []);

  const preferTool = useCallback((toolId: number) => {
    setPreference({ toolId });
  }, []);

  const clearPreferredTool = useCallback(
    () => setPreference((current) => (current === preference ? null : current)),
    [preference],
  );

  return {
    preferredToolId,
    togglePreferredTool,
    preferTool,
    clearPreferredTool,
  };
}
