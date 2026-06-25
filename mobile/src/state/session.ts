// Auth-session store: the Onyx instance URL we target + a coarse auth status.
//
// `serverUrl` persists straight to MMKV (not via zustand's persist) because the HTTP
// layer (`config.ts#getBaseUrl`) reads it *synchronously*, once per request, through
// `getStoredServerUrl`. `status` is in-memory only: `useCurrentUser` (/api/me) is the
// authoritative identity check, except `"anon"` (explicit logout / rejected token), which
// the auth gate treats as a decisive logged-out signal.
import { create } from "zustand";

import { appStorage } from "@/state/storage";

const SERVER_URL_KEY = "onyx.session.server_url";

export type SessionStatus = "loading" | "authed" | "anon";

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
    // Persist before the React update so `getBaseUrl` sees it on the very next request.
    if (serverUrl === null) {
      appStorage.remove(SERVER_URL_KEY);
    } else {
      appStorage.set(SERVER_URL_KEY, serverUrl);
    }
    set({ serverUrl });
  },
}));
