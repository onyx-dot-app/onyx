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
  const publicPromptShortcuts = promptShortcuts.filter((p) => !p.is_public);

  return {
    promptShortcuts,
    publicPromptShortcuts,
    isLoading,
    error,
    refresh: mutate,
  };
}
