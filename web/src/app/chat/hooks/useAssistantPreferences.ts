import useSWR from "swr";
import {
  UserSpecificAssistantPreference,
  UserSpecificAssistantPreferences,
} from "@/lib/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useCallback } from "react";

const ASSISTANT_PREFERENCES_URL = "/api/user/assistant/preferences";

const buildUpdateAssistantPreferenceUrl = (assistantId: number) =>
  `/api/user/assistant/${assistantId}/preferences`;

/**
 * Hook for managing user-specific assistant preferences using SWR.
 * Provides automatic caching, deduplication, and revalidation.
 */
export function useAssistantPreferences() {
  const { data, mutate } = useSWR<UserSpecificAssistantPreferences>(
    ASSISTANT_PREFERENCES_URL,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 60000,
    }
  );

  const setSpecificAssistantPreferences = useCallback(
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
          buildUpdateAssistantPreferenceUrl(assistantId),
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
    assistantPreferences: data ?? null,
    setSpecificAssistantPreferences,
  };
}
