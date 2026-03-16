import { create } from "zustand";

interface GenUIViewStore {
  /** When true, GenUI messages render as structured components.
   *  When false, they fall through to the markdown/text fallback. */
  structuredViewEnabled: boolean;
  toggleStructuredView: () => void;
  /** Reset to structured mode — called when a new message is sent. */
  resetToStructuredView: () => void;
}

export const useGenUIViewStore = create<GenUIViewStore>()((set) => ({
  structuredViewEnabled: true,
  toggleStructuredView: () =>
    set((state) => ({ structuredViewEnabled: !state.structuredViewEnabled })),
  resetToStructuredView: () => set({ structuredViewEnabled: true }),
}));
