import useSWR from "swr";
import { LLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";

export function useLLMProviders(personaId?: number) {
  const url =
    personaId !== undefined
      ? `/api/llm/persona/${personaId}/providers`
      : "/api/llm/provider";

  const { data, error, mutate } = useSWR<LLMProviderDescriptor[]>(
    url,
    errorHandlingFetcher
  );

  return {
    llmProviders: data || [],
    isLoading: !error && !data,
    error,
    refetch: mutate,
  };
}
