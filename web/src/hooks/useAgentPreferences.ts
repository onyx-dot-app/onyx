"use client";

import useSWR from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  UserSpecificAgentPreference,
  UserSpecificAgentPreferences,
} from "@/lib/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useCallback } from "react";

// TODO: rename to agent — https://linear.app/onyx-app/issue/ENG-3766

// TODO: rename to agent — https://linear.app/onyx-app/issue/ENG-3766
const buildUpdateAgentPreferenceUrl = (agentId: number) =>
  `/api/user/assistant/${agentId}/preferences`;

/**
 * Hook for managing user-specific agent preferences using SWR.
 * Provides automatic caching, deduplication, and revalidation.
 */
export default function useAgentPreferences() {
  const { data, mutate } = useSWR<UserSpecificAgentPreferences>(
    SWR_KEYS.agentPreferences,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateIfStale: false,
      dedupingInterval: 60000,
    }
  );

  const setSpecificAgentPreferences = useCallback(
    async (
      agentId: number,
      newAgentPreference: UserSpecificAgentPreference
    ) => {
      // Optimistic update
      mutate(
        {
          ...data,
          [agentId]: newAgentPreference,
        },
        false
      );

      try {
        const response = await fetch(buildUpdateAgentPreferenceUrl(agentId), {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(newAgentPreference),
        });

        if (!response.ok) {
          console.error(
            `Failed to update agent preferences: ${response.status}`
          );
        }
      } catch (error) {
        console.error("Error updating agent preferences:", error);
      }

      // Revalidate after update
      mutate();
    },
    [data, mutate]
  );

  return {
    agentPreferences: data ?? null,
    setSpecificAgentPreferences,
  };
}
