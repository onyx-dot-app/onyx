// TanStack Query client + MMKV-backed persister + the default ClientConfig singleton.
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
import { getApiBaseUrl } from "@/lib/serverUrl";
import { fetch as expoFetch } from "expo/fetch";
import { getAuthHeaders } from "@/auth";
import { makeMmkvStateStorage } from "@/state/persist";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000, // 30s — list/detail data is fresh enough to skip refetch storms
      retry: 1,
      refetchOnWindowFocus: false, // no-op on RN, explicit for web parity
    },
  },
});

// Collapses the common read-hook shape: useQuery on a single string key whose
// queryFn GETs that same key via errorHandlingFetcher.
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

export const clientConfig: ClientConfig = {
  // Getter (not a fixed string): the server URL is chosen at runtime on the domain
  // screen and may not be hydrated yet at module load. The fetcher reads
  // config.baseUrl per request, so this resolves to the live value each call.
  get baseUrl(): string {
    return getApiBaseUrl();
  },
  // expo/fetch (not global RN fetch) — only it exposes a real streaming response.body.
  fetchImpl: expoFetch as unknown as typeof fetch,
  getAuthHeaders, // injects the Bearer JWT from expo-secure-store
};

// Separate MMKV instance from the chat store so query-cache clears can't touch
// persisted chat trees.
export const queryStorage = createMMKV({ id: "onyx.query-cache" });

export const persister = createSyncStoragePersister({
  storage: makeMmkvStateStorage(queryStorage),
});

export const persistMaxAge = 1000 * 60 * 60 * 24; // 24h

// Cache buster: keyed off API base + app build so a backend/app change can't
// restore stale persisted shapes.
export const persistBuster = `${appConfig.apiBaseUrl}|${appConfig.isCloud ? "cloud" : "self"}|v3`;
