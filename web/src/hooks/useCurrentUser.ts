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
 * - `dedupingInterval: 300_000`      — duplicate requests within 5 min are deduped
 *
 * The 5 min window is safe because every path that changes user state
 * busts the cache explicitly:
 * - `logout()` in `@/lib/user` clears `SWR_KEYS.me` after a successful
 *   sign-out so subsequent reads do not return the just-signed-out user.
 * - `useTokenRefresh` calls `onRefreshFail` → `mutateUser()` on token
 *   refresh failure.
 * - `EditUserModal` calls `mutateUser()` after a self role change.
 *
 * @example
 * ```ts
 * const { user, mutateUser, userError } = useCurrentUser();
 * ```
 */
export function useCurrentUser(): {
  /** The authenticated user, `null` when signed out, or `undefined` while loading. */
  user: User | null | undefined;
  /** Imperatively revalidate / update the cached user. */
  mutateUser: KeyedMutator<User | null>;
  /** The error thrown by the fetcher, if any. */
  userError: (Error & { status?: number }) | undefined;
} {
  const { data, mutate, error } = useSWR<User | null>(
    SWR_KEYS.me,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      revalidateIfStale: false,
      dedupingInterval: 300_000,
    }
  );

  return { user: data, mutateUser: mutate, userError: error };
}
