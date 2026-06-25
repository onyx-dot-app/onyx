import { QueryClient, type DehydrateOptions } from "@tanstack/react-query";
import { createSyncStoragePersister } from "@tanstack/query-sync-storage-persister";

import { makeMmkvStorage, queryStorage } from "@/state/storage";
import { isAuthError } from "@/api/errors";
import { QUERY_KEYS } from "@/api/query-keys";

// gcTime is pinned to this below; if an inactive query is GC'd before the persist
// window, the persister rewrites an empty snapshot and the offline cache collapses.
export const persistMaxAge = 1000 * 60 * 60 * 24; // 24h

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: persistMaxAge, // must cover the persist window, see persistMaxAge
      // Don't retry auth/tier errors (401/402/403); they can't succeed without re-auth.
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

// Key prefixes whose data must not hit the unencrypted MMKV snapshot (PII).
// /api/me (email, role) is the only one today; in-memory cache still holds it,
// so a relaunch just refetches. Only the leading entity segment forms the prefix
// since the trailing serverUrl varies per instance.
const NON_PERSISTED_KEY_PREFIXES: readonly (readonly unknown[])[] = [
  [QUERY_KEYS.me(null)[0]],
];

function isNonPersistedKey(queryKey: readonly unknown[]): boolean {
  return NON_PERSISTED_KEY_PREFIXES.some((prefix) =>
    prefix.every((segment, i) => queryKey[i] === segment),
  );
}

export const dehydrateOptions: DehydrateOptions = {
  shouldDehydrateQuery: (query) => {
    if (isNonPersistedKey(query.queryKey)) return false;
    // Library default: only persist successful queries.
    return query.state.status === "success";
  },
};
