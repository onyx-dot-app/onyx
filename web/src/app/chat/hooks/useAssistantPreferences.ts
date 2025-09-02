import {
  UserSpecificAssistantPreference,
  UserSpecificAssistantPreferences,
} from "@/lib/types";
import { useEffect, useState } from "react";

const ASSISTANT_PREFERENCES_URL = "/api/user/assistant/preferences";

const buildUpdateAssistantPreferenceUrl = (assistantId: number) =>
  `/api/user/assistant/${assistantId}/preferences`;

export function useAssistantPreferences() {
  const [assistantPreferences, _setAssistantPreferences] =
    useState<UserSpecificAssistantPreferences | null>(null);

  useEffect(() => {
    const fetchAssistantPreferences = async () => {
      const response = await fetch(ASSISTANT_PREFERENCES_URL);
      const data = await response.json();
      _setAssistantPreferences(data);
    };
    fetchAssistantPreferences();
  }, []);

  const setSpecificAssistantPreferences = async (
    assistantId: number,
    newAssistantPreference: UserSpecificAssistantPreference
  ) => {
    _setAssistantPreferences({
      ...assistantPreferences,
      [assistantId]: newAssistantPreference,
    });

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
  };

  return { assistantPreferences, setSpecificAssistantPreferences };
}
