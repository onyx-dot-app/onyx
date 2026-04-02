"use client";

import useSWR, { mutate } from "swr";
import { useContext } from "react";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SettingsContext } from "@/providers/SettingsProvider";
import { SWR_KEYS } from "@/lib/swr-keys";

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

  const { data, error, isLoading } = useSWR<MinimalUserGroupSnapshot[]>(
    isPaidEnterpriseFeaturesEnabled ? SWR_KEYS.shareableGroups : null,
    errorHandlingFetcher
  );

  const refreshShareableGroups = () => mutate(SWR_KEYS.shareableGroups);

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
