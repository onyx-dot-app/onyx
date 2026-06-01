// Wipe all per-user client state on sign-out. Without this, a different user signing
// in on the same device sees the previous user's chats/cache: the Zustand stores are
// module singletons (survive logout in the same JS session) and MMKV survives across
// launches. Clears BOTH the in-memory stores and the persisted MMKV namespaces.
//
// Imported dynamically by AuthProvider.signOut to avoid an auth <-> query/client cycle.
import { queryClient, queryStorage } from "@/query/client";
import { useChatSessionStore } from "@/state/chatSessionStore";
import { storage } from "@/state/persist";

export function clearUserData(): void {
  // In-memory: the open chat view + all cached server data (sidebar sessions, /me, …).
  useChatSessionStore.getState().reset();
  queryClient.clear();

  // Persisted MMKV:
  //  - onyx.chat        → chat session trees + source preferences
  //  - onyx.query-cache → the React Query persister blob
  storage.clearAll();
  queryStorage.clearAll();
}
