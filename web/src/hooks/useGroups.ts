"use client";

import useSWR, { mutate as globalMutate } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { UserGroup } from "@/lib/types";
import { useContext } from "react";
import { SettingsContext } from "@/providers/SettingsProvider";

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
  const combinedSettings = useContext(SettingsContext);
  const settingsLoading = combinedSettings?.settingsLoading ?? false;
  const isPaidEnterpriseFeaturesEnabled =
    !settingsLoading &&
    combinedSettings &&
    combinedSettings.enterpriseSettings !== null;

  const GROUPS_URL = "/api/manage/admin/user-group";
  const { data, error, isLoading } = useSWR<UserGroup[]>(
    isPaidEnterpriseFeaturesEnabled ? GROUPS_URL : null,
    errorHandlingFetcher
  );

  const refreshGroups = () => globalMutate(GROUPS_URL);

  if (settingsLoading) {
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
