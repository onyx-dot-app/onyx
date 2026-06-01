// Current-user query. GET /api/me returns the User, including
// `preferences.theme_preference` consumed by the theme layer.
import type { User } from "@/lib/types";
import { queryKeys } from "./keys";
import { useSimpleQuery } from "./client";

export function useCurrentUser() {
  return useSimpleQuery<User>(queryKeys.me);
}
