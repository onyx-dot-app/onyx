"use client";

import useSWR from "swr";
import { InputPrompt } from "@/app/chat/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";

export default function usePromptShortcuts() {
  const { data, error, isLoading, mutate } = useSWR<InputPrompt[]>(
    "/api/input_prompt",
    errorHandlingFetcher
  );

  const promptShortcuts = data?.filter((p) => !p.is_public) ?? [];

  return {
    promptShortcuts,
    isLoading,
    error,
    refetch: mutate,
  };
}
