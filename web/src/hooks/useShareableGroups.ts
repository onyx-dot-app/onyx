"use client";

import useSWR, { mutate } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useSettings } from "@/lib/settings/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { Permission } from "@/lib/types";

export interface MinimalUserGroupSnapshot {
  id: number;
  name: string;
}

// TODO (@raunakab):
// Refactor this hook to live inside of a special `ee` directory.

/** `enabled` false skips the fetch, for a dialog that is closed.
 * `manageableFor` keeps only the groups whose shares the user can change with
 * that permission. */
export default function useShareableGroups(
  enabled = true,
  manageableFor?: Permission
) {
  const settings = useSettings();
  const isPaidEnterpriseFeaturesEnabled =
    !settings.isLoading && settings.enterprise !== null;

  const key = manageableFor
    ? SWR_KEYS.shareableGroupsManageableFor(manageableFor)
    : SWR_KEYS.shareableGroups;
  const { data, error, isLoading } = useSWR<MinimalUserGroupSnapshot[]>(
    isPaidEnterpriseFeaturesEnabled && enabled ? key : null,
    errorHandlingFetcher
  );

  const refreshShareableGroups = () => mutate(key);

  if (settings.isLoading) {
    return {
      data: undefined,
      isLoading: true,
      error: undefined,
      refreshShareableGroups,
    };
  }

  if (!isPaidEnterpriseFeaturesEnabled) {
    return {
      data: [],
      isLoading: false,
      error: undefined,
      refreshShareableGroups,
    };
  }

  return {
    data,
    isLoading,
    error,
    refreshShareableGroups,
  };
}
