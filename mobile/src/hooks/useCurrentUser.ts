// Fetches the authenticated user from `/api/me`.
//
// Self-contained (key + queryFn inline), mirroring web's hook-per-file SWR
// pattern. Returns the standard TanStack result: `{ data, error, isPending, ... }`.
// `error` is an `ApiError`; until the login flow lands this resolves to a 403,
// which the auth-aware retry in `query/client.ts` does not retry.
import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/api/client";
import { QUERY_KEYS } from "@/api/query-keys";
import type { CurrentUser } from "@/api/types";
import { useSession } from "@/state/session";

export function useCurrentUser() {
  const serverUrl = useSession((state) => state.serverUrl);
  return useQuery({
    queryKey: QUERY_KEYS.me(serverUrl),
    // `signal` is forwarded so `cancelQueries` can abort the in-flight request.
    queryFn: ({ signal }) => apiFetch<CurrentUser>("/api/me", { signal }),
  });
}
