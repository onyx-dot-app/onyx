import useSWR from "swr";
import { LLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";

export function useLLMProviders() {
  const { data, error, mutate } = useSWR<LLMProviderDescriptor[]>(
    "/api/llm/provider",
    errorHandlingFetcher
  );

  return {
    llmProviders: data || [],
    isLoading: !error && !data,
    error,
    refetch: mutate,
  };
}
