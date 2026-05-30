// Current-user query. GET /api/me returns the User, including
// `preferences.theme_preference` consumed by the theme layer.
import { useQuery } from "@tanstack/react-query";
import { errorHandlingFetcher } from "@/lib/api";
import type { User } from "@/lib/types";
import { queryKeys } from "./keys";
import { clientConfig } from "./client";

export function useCurrentUser() {
  return useQuery({
    queryKey: [queryKeys.me],
    queryFn: () => errorHandlingFetcher<User>(queryKeys.me, clientConfig),
  });
}
