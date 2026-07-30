"use client";

import useSWR, { mutate } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { UserGroup } from "@/lib/types";
import { useSettings } from "@/lib/settings/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";

/**
 * Fetches all user groups in the organization.
 *
 * Returns group information including group members, curators, and associated resources.
 * Use this for displaying group lists in sharing dialogs, admin panels, or permission
 * management interfaces.
 *
 * Note: This hook only returns data if enterprise features are enabled. In non-enterprise
 * environments, it returns an empty array.
 *
 * @returns Object containing:
 *   - data: Array of UserGroup objects, or undefined while loading
 *   - isLoading: Boolean indicating if data is being fetched
 *   - error: Any error that occurred during fetch
 *   - refreshGroups: Function to manually revalidate the data
 *
 * @example
 * // Fetch groups for sharing dialogs
 * const { data: groupsData, isLoading } = useGroups();
 * if (isLoading) return <Spinner />;
 * return <GroupList groups={groupsData ?? []} />;
 *
 * @example
 * // Fetch groups with manual refresh
 * const { data: groupsData, refreshGroups } = useGroups();
 * // Later...
 * await createNewGroup(...);
 * refreshGroups(); // Refresh the group list
 */
export default function useGroups() {
  const settings = useSettings();
  const isPaidEnterpriseFeaturesEnabled =
    !settings.isLoading && settings.enterprise !== null;

  const { data, error, isLoading } = useSWR<UserGroup[]>(
    isPaidEnterpriseFeaturesEnabled ? SWR_KEYS.adminUserGroups : null,
    errorHandlingFetcher
  );

  const refreshGroups = () => mutate(SWR_KEYS.adminUserGroups);

  if (settings.isLoading) {
    return {
      data: undefined,
      isLoading: true,
      error: undefined,
      refreshGroups,
    };
  }

  if (!isPaidEnterpriseFeaturesEnabled) {
    return {
      data: [],
      isLoading: false,
      error: undefined,
      refreshGroups,
    };
  }

  return {
    data,
    isLoading,
    error,
    refreshGroups,
  };
}
