import useSWR from "swr";
import { WellKnownLLMProviderDescriptor } from "@/interfaces/llm";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";

export function useLLMProviderOptions() {
  const { data, error, mutate } = useSWR<
    WellKnownLLMProviderDescriptor[] | undefined
  >(SWR_KEYS.wellKnownLlmProviders, errorHandlingFetcher, {
    revalidateOnFocus: false,
    revalidateIfStale: false,
    dedupingInterval: 60000,
  });

  return {
    llmProviderOptions: data,
    isLoading: !error && !data,
    error,
    refetch: mutate,
  };
}
