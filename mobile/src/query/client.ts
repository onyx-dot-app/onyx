// TanStack Query client + MMKV-backed persister + the default ClientConfig singleton.
//
// The integrator wires <PersistQueryClientProvider client={queryClient}
// persistOptions={{ persister, maxAge, buster }}/> in app/_layout.tsx (see ./client exports).
import {
  QueryClient,
  useQuery,
  type UseQueryOptions,
  type UseQueryResult,
} from "@tanstack/react-query";
import { createSyncStoragePersister } from "@tanstack/query-sync-storage-persister";
import { createMMKV } from "react-native-mmkv";
import { errorHandlingFetcher, type ClientConfig } from "@/lib/api";
import { appConfig } from "@/lib/config";
import { fetch as expoFetch } from "expo/fetch";
import { getAuthHeaders } from "@/auth";
import { makeMmkvStateStorage } from "@/state/persist";

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

// ── Shared read-query helper ─────────────────────────────────────────────────────
// Most read hooks are the identical shape: useQuery on a single string key whose
// queryFn just GETs that same key via errorHandlingFetcher (+ optional overrides
// like a longer staleTime). This collapses that boilerplate to one call.
export function useSimpleQuery<T>(
  key: string,
  opts?: Omit<UseQueryOptions<T, Error, T, [string]>, "queryKey" | "queryFn">
): UseQueryResult<T, Error> {
  return useQuery<T, Error, T, [string]>({
    queryKey: [key],
    queryFn: () => errorHandlingFetcher<T>(key, clientConfig),
    ...opts,
  });
}

// ── Default ClientConfig ───────────────────────────────────────────────────────
// The transport seam consumed by errorHandlingFetcher in every query/mutation.
// Auth: getAuthHeaders (from @/auth) injects the Bearer JWT from secure-store.
export const clientConfig: ClientConfig = {
  baseUrl: appConfig.apiBaseUrl,
  // expo/fetch (not global RN fetch) — only it exposes a real streaming response.body.
  fetchImpl: expoFetch as unknown as typeof fetch,
  getAuthHeaders, // reads the Bearer JWT from expo-secure-store (@/auth)
};

// ── React Query persister (MMKV-backed, synchronous) ────────────────────────────
// A separate MMKV instance from the chat store so query cache eviction/clears can't
// touch persisted chat trees.
const queryStorage = createMMKV({ id: "onyx.query-cache" });

export const persister = createSyncStoragePersister({
  storage: makeMmkvStateStorage(queryStorage),
});

// ── Persist tuning (integrator passes these to PersistQueryClientProvider) ──────
/** Max age of a persisted cache before it's discarded on restore. */
export const persistMaxAge = 1000 * 60 * 60 * 24; // 24h

/**
 * Cache buster — any change invalidates ALL previously-persisted query cache.
 * Keyed off the API base + app build so a backend/app change can't restore stale shapes.
 */
export const persistBuster = `${appConfig.apiBaseUrl}|${appConfig.isCloud ? "cloud" : "self"}|v3`;
