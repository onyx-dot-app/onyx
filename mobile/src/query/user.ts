// GET /api/me — User, including the `theme_preference` the theme layer reads.
import type { User } from "@/lib/types";
import { queryKeys } from "./keys";
import { useSimpleQuery } from "./client";

export function useCurrentUser() {
  return useSimpleQuery<User>(queryKeys.me);
}
