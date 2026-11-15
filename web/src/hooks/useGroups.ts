"use client";

import useSWR, { mutate } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { UserGroup } from "@/lib/types";
import { useSettings } from "@/lib/settings/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";

/** The admin group-list URL. Without members, each group has `users: []`. */
export function userGroupListUrl({
  includeDefault,
  includeMembers,
}: {
  includeDefault: boolean;
  includeMembers: boolean;
}): string {
  const base = includeDefault
    ? SWR_KEYS.adminUserGroupsWithDefault
    : SWR_KEYS.adminUserGroups;
  if (includeMembers) return base;
  return `${base}${base.includes("?") ? "&" : "?"}include_users=false`;
}

/** One group with its members. */
export function userGroupUrl(groupId: number): string {
  return `${SWR_KEYS.adminUserGroups}/${groupId}`;
}

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
 *
 * @param includeDefault Include the seeded Admin and Basic groups, which group
 *   management hides. The service-account forms opt in to grant a key any access.
 * @param includeMembers Load each group's member list. Pass false when the
 *   caller needs only `member_count`: member lists are large in big orgs.
 */
export default function useGroups(
  includeDefault = false,
  includeMembers = true
) {
  const settings = useSettings();
  const isPaidEnterpriseFeaturesEnabled =
    !settings.isLoading && settings.enterprise !== null;

  const url = userGroupListUrl({ includeDefault, includeMembers });

  const { data, error, isLoading } = useSWR<UserGroup[]>(
    isPaidEnterpriseFeaturesEnabled ? url : null,
    errorHandlingFetcher
  );

  // Every variant: callers that edit members share the page with count readers.
  const refreshGroups = () =>
    mutate(
      (key) =>
        typeof key === "string" && key.startsWith(SWR_KEYS.adminUserGroups)
    );

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
