import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";

interface VoiceStatus {
  stt_enabled: boolean;
  tts_enabled: boolean;
  tts_max_speed?: number;
}

export function useVoiceStatus() {
  const { data, error, isLoading } = useSWR<VoiceStatus>(
    SWR_KEYS.voiceStatus,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateIfStale: false,
      dedupingInterval: 60000,
    }
  );

  return {
    sttEnabled: data?.stt_enabled ?? false,
    ttsEnabled: data?.tts_enabled ?? false,
    ttsMaxSpeed: data?.tts_max_speed ?? 2,
    isLoading,
    error,
  };
}
