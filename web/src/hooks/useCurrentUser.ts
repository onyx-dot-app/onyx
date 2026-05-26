import useSWR, { type KeyedMutator } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { User } from "@/lib/types";
import { SWR_KEYS } from "@/lib/swr-keys";

/**
 * Fetches the current authenticated user via SWR (`/api/me`).
 *
 * The hook is mounted in the root `UserProvider`, so every route mount
 * across the app touches this key. Conservative revalidation keeps the
 * fan-out manageable:
 *
 * - `revalidateOnFocus: false`      — tab switches won't trigger a refetch
 * - `revalidateOnReconnect: false`   — network recovery won't trigger a refetch
 * - `dedupingInterval: 60_000`       — duplicate requests within 1 min are deduped
 *
 * Callers that mutate user state (token refresh, profile update) call
 * `mutateUser()` to refetch immediately. Some logout / admin-role-change
 * paths still rely on the dedup window expiring; keep the window short
 * enough that those stale-UI windows match existing behavior.
 *
 * @example
 * ```ts
 * const { user, mutateUser, userError } = useCurrentUser();
 * ```
 */
export function useCurrentUser(): {
  /** The authenticated user, or `undefined` while loading. */
  user: User | undefined;
  /** Imperatively revalidate / update the cached user. */
  mutateUser: KeyedMutator<User>;
  /** The error thrown by the fetcher, if any. */
  userError: (Error & { status?: number }) | undefined;
} {
  const { data, mutate, error } = useSWR<User>(
    SWR_KEYS.me,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      revalidateIfStale: false,
      dedupingInterval: 60_000,
    }
  );

  return { user: data, mutateUser: mutate, userError: error };
}
