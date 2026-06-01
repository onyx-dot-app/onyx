import { useEffect } from "react";
import { create } from "zustand";

import { useChatSessionStore, useCurrentPersonaId } from "./chatSessionStore";

interface ForcedToolsState {
  forcedToolIds: number[];
  toggleForcedTool: (id: number) => void;
  clearForcedTools: () => void;
}

// Mirrors web useForcedTools. The tool forced for the NEXT message (max one);
// not persisted, cleared on session/agent change and after a successful send.
export const useForcedTools = create<ForcedToolsState>((set, get) => ({
  forcedToolIds: [],
  toggleForcedTool: (id) => {
    const { forcedToolIds } = get();
    if (forcedToolIds.includes(id)) set({ forcedToolIds: [] });
    else set({ forcedToolIds: [id] });
  },
  clearForcedTools: () => set({ forcedToolIds: [] }),
}));

// Mount once where the input bar lives: clears the forced tool on session OR
// persona change so a tool forced in one chat/agent never leaks into another.
export function useResetForcedToolsOnSessionChange() {
  const sessionId = useChatSessionStore((s) => s.currentSessionId);
  const personaId = useCurrentPersonaId();
  useEffect(() => {
    useForcedTools.getState().clearForcedTools();
  }, [sessionId, personaId]);
}
