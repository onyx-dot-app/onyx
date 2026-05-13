import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { VoiceProviderView } from "@/lib/voice/interfaces";

export type { VoiceProviderView };

export function useVoiceProviders() {
  const { data, error, isLoading, mutate } = useSWR<VoiceProviderView[]>(
    SWR_KEYS.voiceProviders,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateIfStale: false,
      dedupingInterval: 60000,
    }
  );

  return {
    providers: data ?? [],
    isLoading,
    error,
    refresh: mutate,
  };
}
