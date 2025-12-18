"use client";

import useSWR from "swr";
import {
  UserSpecificAssistantPreference,
  UserSpecificAssistantPreferences,
} from "@/lib/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useCallback } from "react";

interface UseAgentPreferencesOutput {
  agentPreferences: UserSpecificAssistantPreferences | null;
  setAgentPreference: (
    agentId: number,
    preference: UserSpecificAssistantPreference
  ) => Promise<void>;
}

/**
 * Hook for managing user-specific assistant preferences using SWR.
 * Provides automatic caching, deduplication, and revalidation.
 */
export default function useAgentPreferences(): UseAgentPreferencesOutput {
  const { data, mutate } = useSWR<UserSpecificAssistantPreferences>(
    "/api/user/assistant/preferences",
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 60000,
    }
  );

  const setAgentPreference = useCallback(
    async (
      assistantId: number,
      newAssistantPreference: UserSpecificAssistantPreference
    ) => {
      // Optimistic update
      mutate(
        {
          ...data,
          [assistantId]: newAssistantPreference,
        },
        false
      );

      try {
        const response = await fetch(
          `/api/user/assistant/${assistantId}/preferences`,
          {
            method: "PATCH",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify(newAssistantPreference),
          }
        );

        if (!response.ok) {
          console.error(
            `Failed to update assistant preferences: ${response.status}`
          );
        }
      } catch (error) {
        console.error("Error updating assistant preferences:", error);
      }

      // Revalidate after update
      mutate();
    },
    [data, mutate]
  );

  return {
    agentPreferences: data ?? null,
    setAgentPreference,
  };
}
