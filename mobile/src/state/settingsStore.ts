// User-facing app preferences, kept out of chat/session state so a future Settings screen can bind
// switches straight to this store. Persisted directly to MMKV (like session.ts) so choices survive
// relaunch.
import { create } from "zustand";

import { appStorage } from "@/state/storage";

const AUTO_SCROLL_ENABLED_KEY = "onyx.settings.auto_scroll_enabled";

function readAutoScrollEnabled(): boolean {
  // Default ON (unset key): following the latest turn while streaming is the expected chat default.
  return appStorage.getBoolean(AUTO_SCROLL_ENABLED_KEY) ?? true;
}

interface SettingsState {
  // When off, the chat list never auto-follows the streaming turn (the jump-to-bottom button still
  // works). Wire this to a Settings toggle later; flip it now via useSettings.getState().
  autoScrollEnabled: boolean;
  setAutoScrollEnabled: (enabled: boolean) => void;
}

export const useSettings = create<SettingsState>((set) => ({
  autoScrollEnabled: readAutoScrollEnabled(),
  setAutoScrollEnabled: (autoScrollEnabled) => {
    appStorage.set(AUTO_SCROLL_ENABLED_KEY, autoScrollEnabled);
    set({ autoScrollEnabled });
  },
}));
