// Auth-session store: which Onyx instance we point at + a coarse auth status.
//
// `serverUrl` is the user-entered base URL of their Onyx instance (cloud or
// self-hosted) — the runtime replacement for the build-time EXPO_PUBLIC_API_URL.
// It must be readable *synchronously* by the HTTP layer (`config.ts#getBaseUrl`,
// called once per request), so it is persisted directly to MMKV under a
// dedicated key rather than through zustand's persist envelope. The synchronous
// `getStoredServerUrl()` is the read path `getBaseUrl` uses.
//
// `status` is a coarse, in-memory signal SessionManager flips on login/logout
// for immediate UI feedback. The authoritative identity check remains
// `useCurrentUser` (/api/me); `status` is intentionally NOT persisted.
import { create } from "zustand";

import { appStorage } from "@/state/storage";

const SERVER_URL_KEY = "onyx.session.server_url";

export type SessionStatus = "loading" | "authed" | "anon";

// Synchronous read of the persisted server URL. Used by `getBaseUrl` (which
// runs outside React, per request) and to seed the store's initial value.
export function getStoredServerUrl(): string | null {
  return appStorage.getString(SERVER_URL_KEY) ?? null;
}

interface SessionState {
  status: SessionStatus;
  serverUrl: string | null;
  setStatus: (status: SessionStatus) => void;
  setServerUrl: (serverUrl: string | null) => void;
}

export const useSession = create<SessionState>((set) => ({
  status: "loading",
  serverUrl: getStoredServerUrl(),
  setStatus: (status) => set({ status }),
  setServerUrl: (serverUrl) => {
    // Persist immediately so `getBaseUrl` (which reads MMKV directly) sees the
    // new URL on the very next request, before any React re-render settles.
    if (serverUrl === null) {
      appStorage.remove(SERVER_URL_KEY);
    } else {
      appStorage.set(SERVER_URL_KEY, serverUrl);
    }
    set({ serverUrl });
  },
}));
