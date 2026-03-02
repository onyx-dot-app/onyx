"use client";

import useSWR from "swr";
import {
  UserSpecificAgentPreference,
  UserSpecificAgentPreferences,
} from "@/lib/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useCallback } from "react";

// TODO: rename to agent — https://linear.app/onyx-app/issue/ENG-3766
const AGENT_PREFERENCES_URL = "/api/user/assistant/preferences";

// TODO: rename to agent — https://linear.app/onyx-app/issue/ENG-3766
const buildUpdateAgentPreferenceUrl = (agentId: number) =>
  `/api/user/assistant/${agentId}/preferences`;

/**
 * Hook for managing user-specific agent preferences using SWR.
 * Provides automatic caching, deduplication, and revalidation.
 */
export default function useAgentPreferences() {
  const { data, mutate } = useSWR<UserSpecificAgentPreferences>(
    AGENT_PREFERENCES_URL,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
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
