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

/*
 * Never written to the unencrypted MMKV snapshot: message content, plus anything naming a person
 * or a workspace (identity, agent and project names, file names). Prefixes match only the leading
 * entity segment because the trailing serverUrl varies per instance.
 *
 * The bar is what stays legible on disk, NOT per-user-ness — a switched account is already covered
 * by `purgeCache` (sessionManager), which drops the in-memory and on-disk caches on login and on
 * logout alike. So the source-picker keys stay out of this list on purpose: connector *types* and
 * per-agent tool ids are opaque without the agent names excluded above, and persisting them is what
 * lets a send moments after launch honour the user's saved source and tool choices rather than
 * guess at them.
 */
const NON_PERSISTED_KEY_PREFIXES: readonly (readonly unknown[])[] = [
  [QUERY_KEYS.me(null)[0]],
  [QUERY_KEYS.agents(null)[0]],
  [QUERY_KEYS.workspaceSettings(null)[0]],
  [QUERY_KEYS.userProjects(null)[0]],
  [QUERY_KEYS.userProject(null, null)[0]],
  [QUERY_KEYS.userRecentFiles(null)[0]],
];

function isNonPersistedKey(queryKey: readonly unknown[]): boolean {
  // Default-deny so a future `chat-*` key is excluded without being listed.
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
