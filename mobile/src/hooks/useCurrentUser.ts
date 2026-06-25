// Fetches the authenticated user from `/api/me` — the auth gate's identity probe.
import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/api/client";
import { QUERY_KEYS } from "@/api/query-keys";
import type { CurrentUser } from "@/api/types";
import { useSession } from "@/state/session";

export function useCurrentUser() {
  const serverUrl = useSession((state) => state.serverUrl);
  return useQuery({
    queryKey: QUERY_KEYS.me(serverUrl),
    // Idle until connected: no serverUrl → `getBaseUrl()` throws (not a 401). Like `useAuthConfig`.
    enabled: serverUrl !== null,
    queryFn: ({ signal }) => apiFetch<CurrentUser>("/me", { signal }),
  });
}
