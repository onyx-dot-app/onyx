import { QueryClient, type DehydrateOptions } from "@tanstack/react-query";
import { createSyncStoragePersister } from "@tanstack/query-sync-storage-persister";

import { makeMmkvStorage, queryStorage } from "@/state/storage";
import { isAuthError } from "@/api/errors";
import { QUERY_KEYS } from "@/api/query-keys";

export const persistMaxAge = 1000 * 60 * 60 * 24;

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: persistMaxAge, // must cover the persist window or the offline cache collapses
      // 401/402/403 can't succeed without re-auth.
      retry: (failureCount, error) => !isAuthError(error) && failureCount < 1,
      // Must stay true or the AppState->focusManager bridge in query/focus.ts no-ops.
      refetchOnWindowFocus: true,
      refetchOnReconnect: true,
    },
  },
});

export const persister = createSyncStoragePersister({
  storage: makeMmkvStorage(queryStorage),
});

// Keys excluded from the unencrypted MMKV snapshot. Identity (`me`), ALL chat data,
// workspace-scoped config (agents, settings), and projects (their embedded chat titles
// are PII) live in memory only and refetch on launch, so nothing personal or
// workspace-specific lingers after logout or an account switch (the trailing serverUrl
// varies per instance, so only the leading entity segment matches).
const NON_PERSISTED_KEY_PREFIXES: readonly (readonly unknown[])[] = [
  [QUERY_KEYS.me(null)[0]],
  [QUERY_KEYS.agents(null)[0]],
  [QUERY_KEYS.workspaceSettings(null)[0]],
  [QUERY_KEYS.userProjects(null)[0]], // "projects"
  [QUERY_KEYS.userProject(null, null)[0]], // "project"
  [QUERY_KEYS.userRecentFiles(null)[0]], // "recent-files" (file names are PII)
];

function isNonPersistedKey(queryKey: readonly unknown[]): boolean {
  // Default-deny for chat: any key whose entity segment starts with `chat-` (covers
  // chat-sessions/chat-session today + future chat-message/history keys) never persists.
  const head = queryKey[0];
  if (typeof head === "string" && head.startsWith("chat-")) return true;
  return NON_PERSISTED_KEY_PREFIXES.some((prefix) =>
    prefix.every((segment, i) => queryKey[i] === segment),
  );
}

export const dehydrateOptions: DehydrateOptions = {
  shouldDehydrateQuery: (query) => {
    if (isNonPersistedKey(query.queryKey)) return false;
    return query.state.status === "success";
  },
};
