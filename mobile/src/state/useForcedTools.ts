import { create } from "zustand";

interface ForcedToolsState {
  forcedToolIds: number[];
  setForcedToolIds: (ids: number[]) => void;
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
  setForcedToolIds: (ids) => set({ forcedToolIds: ids }),
  toggleForcedTool: (id) => {
    const { forcedToolIds } = get();
    if (forcedToolIds.includes(id)) set({ forcedToolIds: [] });
    else set({ forcedToolIds: [id] });
  },
  clearForcedTools: () => set({ forcedToolIds: [] }),
}));
