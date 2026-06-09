// TanStack Query client + MMKV-backed persister.
import { QueryClient } from "@tanstack/react-query";
import { createSyncStoragePersister } from "@tanstack/query-sync-storage-persister";

import { makeMmkvStorage, queryStorage } from "@/state/storage";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000, // 30s — fresh enough to skip refetch storms
      retry: 1,
      refetchOnWindowFocus: false, // no-op on RN, explicit for parity
    },
  },
});

export const persister = createSyncStoragePersister({
  storage: makeMmkvStorage(queryStorage),
});

export const persistMaxAge = 1000 * 60 * 60 * 24; // 24h
