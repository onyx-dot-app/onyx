// TanStack Query client + MMKV-backed persister + the default ClientConfig singleton.
//
// The integrator wires <PersistQueryClientProvider client={queryClient}
// persistOptions={{ persister, maxAge, buster }}/> in app/_layout.tsx (see ./client exports).
import { QueryClient } from "@tanstack/react-query";
import { createSyncStoragePersister } from "@tanstack/query-sync-storage-persister";
import { createMMKV } from "react-native-mmkv";
import type { ClientConfig } from "@/lib/api";
import { appConfig } from "@/lib/config";

// ── QueryClient ────────────────────────────────────────────────────────────────
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000, // 30s — list/detail data is fresh enough to skip refetch storms
      retry: 1,
      refetchOnWindowFocus: false, // no-op on RN, but explicit for clarity/web parity
    },
  },
});

// ── Default ClientConfig ───────────────────────────────────────────────────────
// The transport seam consumed by errorHandlingFetcher in every query/mutation.
// For now auth headers are empty; doc 07 swaps getAuthHeaders to inject a Bearer PAT.
export const clientConfig: ClientConfig = {
  baseUrl: appConfig.apiBaseUrl,
  fetchImpl: fetch, // global fetch for now; doc 07 may swap to expo/fetch for streaming
  getAuthHeaders: async () => ({}), // TODO(07): inject `Authorization: Bearer onyx_pat_...`
};

// ── React Query persister (MMKV-backed, synchronous) ────────────────────────────
// A separate MMKV instance from the chat store so query cache eviction/clears can't
// touch persisted chat trees.
const queryStorage = createMMKV({ id: "onyx.query-cache" });

export const persister = createSyncStoragePersister({
  storage: {
    getItem: (key) => queryStorage.getString(key) ?? null,
    setItem: (key, value) => {
      queryStorage.set(key, value);
    },
    removeItem: (key) => {
      queryStorage.remove(key);
    },
  },
});

// ── Persist tuning (integrator passes these to PersistQueryClientProvider) ──────
/** Max age of a persisted cache before it's discarded on restore. */
export const persistMaxAge = 1000 * 60 * 60 * 24; // 24h

/**
 * Cache buster — any change invalidates ALL previously-persisted query cache.
 * Keyed off the API base + app build so a backend/app change can't restore stale shapes.
 */
export const persistBuster = `${appConfig.apiBaseUrl}|${appConfig.isCloud ? "cloud" : "self"}`;
