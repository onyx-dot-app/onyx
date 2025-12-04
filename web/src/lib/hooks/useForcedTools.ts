import { create } from "zustand";

interface ForcedToolsState {
  forcedToolIds: number[];
  setForcedToolIds: (ids: number[]) => void;
  toggleForcedTool: (id: number) => void;
  clearForcedTools: () => void;
}

/**
 * Zustand store for managing forced tool IDs.
 * This is local UI state - tools that are forced to be used in the next message.
 *
 * When a tool is "forced", it will be included in the next chat request
 * regardless of whether the LLM would normally choose to use it.
 */
export const useForcedTools = create<ForcedToolsState>((set, get) => ({
  forcedToolIds: [],

  setForcedToolIds: (ids) => set({ forcedToolIds: ids }),

  toggleForcedTool: (id) => {
    const { forcedToolIds } = get();
    if (forcedToolIds.includes(id)) {
      // If clicking already forced tool, clear all forced tools
      set({ forcedToolIds: [] });
    } else {
      // Replace with single forced tool
      set({ forcedToolIds: [id] });
    }
  },

  clearForcedTools: () => set({ forcedToolIds: [] }),
}));
