import useSWR from "swr";
import {
  LLMProviderName,
  WellKnownLLMProviderDescriptor,
} from "@/lib/languageModels/types";
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
    llmProviderOptions: data?.filter(
      (provider) => provider.name !== LLMProviderName.TYPESAFE
    ),
    isLoading: !error && !data,
    error,
    refetch: mutate,
  };
}
