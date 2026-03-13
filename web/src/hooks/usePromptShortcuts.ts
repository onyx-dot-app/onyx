"use client";

import useSWR from "swr";
import { InputPrompt } from "@/app/app/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";

export default function usePromptShortcuts(personaId?: number) {
  const query = personaId !== undefined ? `?persona_id=${personaId}` : "";
  const { data, error, isLoading, mutate } = useSWR<InputPrompt[]>(
    `/api/input_prompt${query}`,
    errorHandlingFetcher
  );

  const promptShortcuts = data ?? [];
  const userPromptShortcuts = promptShortcuts.filter((p) => !p.is_public);
  const activePromptShortcuts = promptShortcuts.filter((p) => p.active);

  return {
    promptShortcuts,
    userPromptShortcuts,
    activePromptShortcuts,
    isLoading,
    error,
    refresh: mutate,
  };
}
