"use client";

import useSWR from "swr";
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
  const isPaidEnterpriseFeaturesEnabled =
    combinedSettings && combinedSettings.enterpriseSettings !== null;

  const { data, error, mutate, isLoading } = useSWR<UserGroup[]>(
    isPaidEnterpriseFeaturesEnabled ? "/api/manage/admin/user-group" : null,
    errorHandlingFetcher
  );

  // If enterprise features are not enabled, return empty array
  if (!isPaidEnterpriseFeaturesEnabled) {
    return {
      data: [],
      isLoading: false,
      error: undefined,
      refreshGroups: () => {},
    };
  }

  return {
    data,
    isLoading,
    error,
    refreshGroups: mutate,
  };
}
