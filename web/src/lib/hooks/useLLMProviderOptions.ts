import useSWR from "swr";
import { WellKnownLLMProviderDescriptor } from "@/lib/languageModels/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { getProvider } from "@/lib/languageModels/utils";

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
      (provider) => !getProvider(provider.name).decisionOnly
    ),
    isLoading: !error && !data,
    error,
    refetch: mutate,
  };
}
