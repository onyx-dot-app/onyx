"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { AllUsersResponse } from "@/lib/types";

export interface UseUsersParams {
  includeApiKeys: boolean;
}

/**
 * Fetches all users in the organization.
 *
 * Returns user information including accepted users, invited users, and optionally
 * API key users. Use this for displaying user lists in sharing dialogs, admin panels,
 * or permission management interfaces.
 *
 * @param params - Configuration object
 * @param params.includeApiKeys - Whether to include API key users in the response
 *
 * @returns Object containing:
 *   - data: AllUsersResponse containing accepted, invited, and API key users, or undefined while loading
 *   - isLoading: Boolean indicating if data is being fetched
 *   - error: Any error that occurred during fetch
 *   - refreshUsers: Function to manually revalidate the data
 *
 * @example
 * // Fetch users without API keys (for sharing dialogs)
 * const { data: usersData, isLoading } = useUsers({ includeApiKeys: false });
 * if (isLoading) return <Spinner />;
 * return <UserList users={usersData?.accepted ?? []} />;
 *
 * @example
 * // Fetch all users including API keys (for admin panel)
 * const { data: usersData, refreshUsers } = useUsers({ includeApiKeys: true });
 * // Later...
 * await createNewUser(...);
 * refreshUsers(); // Refresh the user list
 */
export default function useUsers({ includeApiKeys }: UseUsersParams) {
  const { data, error, mutate, isLoading } = useSWR<AllUsersResponse>(
    `/api/manage/users?include_api_keys=${includeApiKeys}`,
    errorHandlingFetcher
  );

  return {
    data,
    isLoading,
    error,
    refreshUsers: mutate,
  };
}
