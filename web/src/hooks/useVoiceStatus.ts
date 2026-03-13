import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";

interface VoiceStatus {
  stt_enabled: boolean;
  tts_enabled: boolean;
}

export function useVoiceStatus() {
  const { data, error, isLoading } = useSWR<VoiceStatus>(
    "/api/voice/status",
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 60000,
    }
  );

  return {
    sttEnabled: data?.stt_enabled ?? false,
    ttsEnabled: data?.tts_enabled ?? false,
    isLoading,
    error,
  };
}
