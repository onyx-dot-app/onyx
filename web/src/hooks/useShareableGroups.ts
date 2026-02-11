"use client";

import useSWR from "swr";
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
  const isPaidEnterpriseFeaturesEnabled =
    combinedSettings && combinedSettings.enterpriseSettings !== null;

  const { data, error, mutate, isLoading } = useSWR<MinimalUserGroupSnapshot[]>(
    isPaidEnterpriseFeaturesEnabled ? "/api/manage/user-groups/minimal" : null,
    errorHandlingFetcher
  );

  if (!isPaidEnterpriseFeaturesEnabled) {
    return {
      data: [],
      isLoading: false,
      error: undefined,
      refreshShareableGroups: () => {},
    };
  }

  return {
    data,
    isLoading,
    error,
    refreshShareableGroups: mutate,
  };
}
