"use client";

import useSWR, { mutate } from "swr";
import { useContext } from "react";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SettingsContext } from "@/providers/SettingsProvider";

export interface MinimalUserGroupSnapshot {
  id: number;
  name: string;
}

// TODO (@raunakab):
// Refactor this hook to live inside of a special `ee` directory.

export default function useShareableGroups() {
  const combinedSettings = useContext(SettingsContext);
  const settingsLoading = combinedSettings?.settingsLoading ?? false;
  const isPaidEnterpriseFeaturesEnabled =
    !settingsLoading &&
    combinedSettings &&
    combinedSettings.enterpriseSettings !== null;

  const SHAREABLE_GROUPS_URL = "/api/manage/user-groups/minimal";
  const { data, error, isLoading } = useSWR<MinimalUserGroupSnapshot[]>(
    isPaidEnterpriseFeaturesEnabled ? SHAREABLE_GROUPS_URL : null,
    errorHandlingFetcher
  );

  const refreshShareableGroups = () => mutate(SHAREABLE_GROUPS_URL);

  if (settingsLoading) {
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
