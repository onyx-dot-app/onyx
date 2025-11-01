import { useRef } from "react";
import useSWR from "swr";
import { LLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";

export function useLLMProviders(personaId?: number) {
  const url =
    personaId !== undefined
      ? `/api/llm/persona/${personaId}/providers`
      : "/api/llm/provider";

  // Stable empty array reference to avoid creating new arrays on every render
  const emptyArrayRef = useRef<LLMProviderDescriptor[]>([]);

  const { data, error, mutate } = useSWR<LLMProviderDescriptor[]>(
    url,
    errorHandlingFetcher
  );

  return {
    llmProviders: data || emptyArrayRef.current,
    isLoading: !error && !data,
    error,
    refetch: mutate,
  };
}
