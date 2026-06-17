// Discovers the connected instance's auth configuration (`/api/auth/type`):
// which login methods to show + password rules. This is a *public* endpoint
// (auth:false) — it's what we call before the user has a token. Keyed by
// serverUrl so switching instances refetches against the new backend.
import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/api/client";
import { QUERY_KEYS } from "@/api/query-keys";
import type { AuthTypeMetadata } from "@/api/types";
import { useSession } from "@/state/session";

export function useAuthConfig() {
  const serverUrl = useSession((state) => state.serverUrl);
  return useQuery({
    queryKey: QUERY_KEYS.authType(serverUrl),
    queryFn: ({ signal }) =>
      apiFetch<AuthTypeMetadata>("/api/auth/type", { auth: false, signal }),
  });
}
