// Public endpoint (auth:false) called before the user has a token; keyed by serverUrl so switching instances refetches.
import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/api/client";
import { QUERY_KEYS } from "@/api/query-keys";
import type { AuthTypeMetadata } from "@/api/types";
import { useSession } from "@/state/session";

export function useAuthConfig() {
  const serverUrl = useSession((state) => state.serverUrl);
  return useQuery({
    queryKey: QUERY_KEYS.authType(serverUrl),
    // Idle until connected: without a URL getBaseUrl() throws a plain Error, which TanStack would retry and park in error state.
    enabled: serverUrl !== null,
    queryFn: ({ signal }) =>
      apiFetch<AuthTypeMetadata>("/auth/type", { auth: false, signal }),
  });
}
