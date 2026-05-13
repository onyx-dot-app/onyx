import { SvgAzure, SvgElevenLabs, SvgOpenai } from "@opal/logos";
import { SvgMicrophone } from "@opal/icons";
import type { IconProps } from "@opal/types";

/** Whether the provider is being configured for speech-to-text or text-to-speech. */
export type ProviderMode = "stt" | "tts";

/** All static display and configuration data for a single voice provider. */
export interface VoiceProviderDetail {
  label: string;
  icon: React.FunctionComponent<IconProps>;
  /** Link to the provider's API key management page. */
  apiKeyUrl?: string;
  /** Link to the provider's general documentation. */
  docsUrl?: string;
  /** Link to the provider's voice/language reference, shown in the TTS voice picker. */
  voiceDocsUrl?: { url: string; label: string };
  /** Selectable STT models for this provider. Omit if the provider has no STT model choice. */
  sttModels?: Array<{ id: string; name: string }>;
  /** Selectable TTS models for this provider. Omit if the provider has no TTS model choice. */
  ttsModels?: Array<{ id: string; name: string }>;
}

const DEFAULT_VOICE_PROVIDER_DETAIL: VoiceProviderDetail = {
  label: "",
  icon: SvgMicrophone,
};

/** Per-provider static details, keyed by provider_type. */
export const VOICE_PROVIDER_DETAILS: Record<string, VoiceProviderDetail> = {
  openai: {
    label: "OpenAI",
    icon: SvgOpenai,
    apiKeyUrl: "https://platform.openai.com/api-keys",
    docsUrl: "https://platform.openai.com/docs/guides/text-to-speech",
    voiceDocsUrl: {
      url: "https://platform.openai.com/docs/guides/text-to-speech#voice-options",
      label: "OpenAI",
    },
    sttModels: [{ id: "whisper-1", name: "Whisper v1" }],
    ttsModels: [
      { id: "tts-1", name: "TTS-1" },
      { id: "tts-1-hd", name: "TTS-1 HD" },
    ],
  },
  azure: {
    label: "Azure Speech Services",
    icon: SvgAzure,
    apiKeyUrl: "https://portal.azure.com/",
    docsUrl:
      "https://learn.microsoft.com/en-us/azure/ai-services/speech-service/",
    voiceDocsUrl: {
      url: "https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support?tabs=tts",
      label: "Azure",
    },
  },
  elevenlabs: {
    label: "ElevenLabs",
    icon: SvgElevenLabs,
    apiKeyUrl: "https://elevenlabs.io/app/settings/api-keys",
    docsUrl: "https://elevenlabs.io/docs",
    voiceDocsUrl: {
      url: "https://elevenlabs.io/docs/voices/premade-voices",
      label: "ElevenLabs",
    },
  },
};

/** Returns the detail entry for a provider type, falling back to a generic entry for unknown types. */
export function getVoiceProviderDetail(
  providerType: string
): VoiceProviderDetail {
  return (
    VOICE_PROVIDER_DETAILS[providerType] ?? {
      ...DEFAULT_VOICE_PROVIDER_DETAIL,
      label: providerType,
    }
  );
}

/** Maps card-level model IDs to actual API model IDs. IDs absent from this map are used as-is. */
export const MODEL_ID_MAP: Record<string, string> = {
  whisper: "whisper-1",
};

/** Resolves a card-level model ID to the API model ID expected by the backend. */
export function resolveModelId(cardId: string): string {
  return MODEL_ID_MAP[cardId] ?? cardId;
}
