"use client";

import useSWR from "swr";
import { InputPrompt } from "@/app/chat/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";

export default function usePromptShortcuts() {
  const { data, error, isLoading, mutate } = useSWR<InputPrompt[]>(
    "/api/input_prompt",
    errorHandlingFetcher
  );

  const promptShortcuts = data ?? [];
  const userPromptShortcuts = promptShortcuts.filter((p) => !p.is_public);

  return {
    promptShortcuts,
    userPromptShortcuts,
    isLoading,
    error,
    refresh: mutate,
  };
}
