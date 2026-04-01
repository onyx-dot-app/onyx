import useSWR, { type KeyedMutator } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { User } from "@/lib/types";
import { SWR_KEYS } from "@/lib/swr-keys";

/**
 * Fetches the current authenticated user via SWR (`/api/me`).
 *
 * This hook is intentionally configured with conservative revalidation
 * settings to avoid hammering the backend on every focus/reconnect event:
 *
 * - `revalidateOnFocus: false`      — tab switches won't trigger a refetch
 * - `revalidateOnReconnect: false`   — network recovery won't trigger a refetch
 * - `dedupingInterval: 30_000`       — duplicate requests within 30 s are deduped
 *
 * The returned `mutateUser` handle lets callers imperatively refetch (e.g.
 * after a token refresh) without changing the global SWR config.
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
      dedupingInterval: 30_000,
    }
  );

  return { user: data, mutateUser: mutate, userError: error };
}
