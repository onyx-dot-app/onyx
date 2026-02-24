import useSWR from "swr";
import { WellKnownLLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";

export function useLLMProviderOptions() {
  const { data, error, mutate } = useSWR<
    WellKnownLLMProviderDescriptor[] | undefined
  >("/api/admin/llm/built-in/options", errorHandlingFetcher, {
    revalidateOnFocus: false,
    dedupingInterval: 60000, // Dedupe requests within 1 minute
  });

  return {
    llmProviderOptions: data,
    isLoading: !error && !data,
    error,
    refetch: mutate,
  };
}
