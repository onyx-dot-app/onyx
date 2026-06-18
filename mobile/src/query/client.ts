// TanStack Query client + MMKV-backed persister.
import { QueryClient, type DehydrateOptions } from "@tanstack/react-query";
import { createSyncStoragePersister } from "@tanstack/query-sync-storage-persister";

import { makeMmkvStorage, queryStorage } from "@/state/storage";
import { isAuthError } from "@/api/errors";
import { QUERY_KEYS } from "@/api/query-keys";

// How long a restored MMKV snapshot stays valid (24h). gcTime is pinned to this
// below: an inactive query must live in the in-memory cache at least as long as
// the persist window, otherwise it's garbage-collected after the default 5 min,
// the persister rewrites an empty snapshot, and the 24h offline cache silently
// collapses to ~5 min.
export const persistMaxAge = 1000 * 60 * 60 * 24; // 24h

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000, // 30s — fresh enough to skip refetch storms
      gcTime: persistMaxAge, // keep inactive queries for the full persist window
      // Don't retry auth/tier errors (401/402/403) — retrying just spams the
      // backend with requests that can't succeed without re-auth. Otherwise
      // retry once. Mirrors web's `skipRetryOnAuthError`.
      retry: (failureCount, error) => !isAuthError(error) && failureCount < 1,
      // Refetch stale data when the app returns to the foreground. On RN this is
      // driven by the AppState -> focusManager bridge in `query/focus.ts`; this
      // flag must stay true (its default) or that bridge becomes a no-op.
      refetchOnWindowFocus: true,
      refetchOnReconnect: true, // refetch stale data when connectivity returns
    },
  },
});

export const persister = createSyncStoragePersister({
  storage: makeMmkvStorage(queryStorage),
});

// Query-key prefixes whose data is identity PII (or otherwise must not be
// written to disk). The MMKV query-cache snapshot is unencrypted: a secure
// encryption key would have to be fetched asynchronously from the keychain
// before the synchronous MMKV instance is created — fragile — so instead we keep
// PII out of the persisted snapshot entirely. /api/me (email, role) is the only
// such query today. The in-memory cache still holds it for the session; only
// persistence is skipped, so a relaunch refetches it (and the auth gate shows a
// brief splash).
//
// Matched structurally, segment by segment (see `isNonPersistedKey`), so the
// whole `["me", serverUrl]` family is excluded for any serverUrl while an
// unrelated key such as `["me-preferences"]` is not. The trailing serverUrl
// varies per instance, so only the leading entity segment forms the prefix.
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
    // Otherwise keep the library default: only persist successful queries.
    return query.state.status === "success";
  },
};
