import { useEffect } from "react";
import { create } from "zustand";

import { useChatSessionStore, useCurrentPersonaId } from "./chatSessionStore";

interface ForcedToolsState {
  forcedToolIds: number[];
  toggleForcedTool: (id: number) => void;
  clearForcedTools: () => void;
}

/**
 * Ephemeral UI state — the tool forced for the NEXT message (max one).
 * Mirrors web/src/lib/hooks/useForcedTools.ts. Not persisted; cleared on
 * session/agent change and after a successful send.
 */
export const useForcedTools = create<ForcedToolsState>((set, get) => ({
  forcedToolIds: [],
  toggleForcedTool: (id) => {
    const { forcedToolIds } = get();
    if (forcedToolIds.includes(id)) set({ forcedToolIds: [] });
    else set({ forcedToolIds: [id] });
  },
  clearForcedTools: () => set({ forcedToolIds: [] }),
}));

/**
 * Clears the forced tool whenever the current session OR the current agent
 * (persona) changes. Web resets forced tools on both transitions; mount this
 * once where the chat input bar lives so a tool forced in one chat/agent never
 * leaks into another.
 */
export function useResetForcedToolsOnSessionChange() {
  const sessionId = useChatSessionStore((s) => s.currentSessionId);
  const personaId = useCurrentPersonaId();
  useEffect(() => {
    useForcedTools.getState().clearForcedTools();
  }, [sessionId, personaId]);
}
