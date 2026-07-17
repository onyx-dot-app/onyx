import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/api/client";
import { QUERY_KEYS } from "@/api/query-keys";
import type { CurrentUser } from "@/api/types";
import { useSession } from "@/state/session";

export function useCurrentUser() {
  const serverUrl = useSession((state) => state.serverUrl);
  return useQuery({
    queryKey: QUERY_KEYS.me(serverUrl),
    // No serverUrl → `getBaseUrl()` throws (not a 401), so stay idle until connected.
    enabled: serverUrl !== null,
    queryFn: ({ signal }) => apiFetch<CurrentUser>("/me", { signal }),
  });
}
