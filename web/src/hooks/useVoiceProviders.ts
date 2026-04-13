import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";

export interface VoiceProviderView {
  id: number;
  name: string;
  provider_type: string;
  is_default_stt: boolean;
  is_default_tts: boolean;
  stt_model: string | null;
  tts_model: string | null;
  default_voice: string | null;
  has_api_key: boolean;
  target_uri: string | null;
}

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
