"use client";

import useSWR, { mutate } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useSettings } from "@/lib/settings/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";

export interface MinimalUserGroupSnapshot {
  id: number;
  name: string;
}

// TODO (@raunakab):
// Refactor this hook to live inside of a special `ee` directory.

export default function useShareableGroups() {
  const settings = useSettings();
  const isPaidEnterpriseFeaturesEnabled =
    !settings.isLoading && settings.enterprise !== null;

  const { data, error, isLoading } = useSWR<MinimalUserGroupSnapshot[]>(
    isPaidEnterpriseFeaturesEnabled ? SWR_KEYS.shareableGroups : null,
    errorHandlingFetcher
  );

  const refreshShareableGroups = () => mutate(SWR_KEYS.shareableGroups);

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
