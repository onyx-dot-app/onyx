import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/api/client";
import { QUERY_KEYS } from "@/api/query-keys";
import type { AuthTypeMetadata } from "@/api/types";
import { useSession } from "@/state/session";

export function useAuthConfig() {
  const serverUrl = useSession((state) => state.serverUrl);
  return useQuery({
    queryKey: QUERY_KEYS.authType(serverUrl),
    // Without a URL getBaseUrl() throws; staying idle avoids a parked error state.
    enabled: serverUrl !== null,
    queryFn: ({ signal }) =>
      apiFetch<AuthTypeMetadata>("/auth/type", { auth: false, signal }),
  });
}
