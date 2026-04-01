"use client";

import useSWR from "swr";
import { InputPrompt } from "@/app/app/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";

export default function usePromptShortcuts() {
  const { data, error, isLoading, mutate } = useSWR<InputPrompt[]>(
    SWR_KEYS.promptShortcuts,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateIfStale: false,
      dedupingInterval: 60000,
    }
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
