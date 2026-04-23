import { SvgAzure, SvgElevenLabs, SvgOpenai } from "@opal/logos";
import { SvgMicrophone } from "@opal/icons";
import type { IconProps } from "@opal/types";

export type VoiceProviderType = "openai" | "azure" | "elevenlabs";
export type ProviderMode = "stt" | "tts";

export function getProviderIcon(
  providerType: VoiceProviderType | (string & {})
): React.FunctionComponent<IconProps> {
  switch (providerType) {
    case "openai":
      return SvgOpenai;
    case "azure":
      return SvgAzure;
    case "elevenlabs":
      return SvgElevenLabs;
    default:
      return SvgMicrophone;
  }
}

export function getProviderLabel(
  providerType: VoiceProviderType | (string & {})
): string {
  switch (providerType) {
    case "openai":
      return "OpenAI";
    case "azure":
      return "Azure";
    case "elevenlabs":
      return "ElevenLabs";
    default:
      return providerType;
  }
}

export const PROVIDER_LABELS: Record<string, string> = {
  openai: "OpenAI",
  azure: "Azure Speech Services",
  elevenlabs: "ElevenLabs",
};

export const PROVIDER_API_KEY_URLS: Record<string, string> = {
  openai: "https://platform.openai.com/api-keys",
  azure: "https://portal.azure.com/",
  elevenlabs: "https://elevenlabs.io/app/settings/api-keys",
};

export const PROVIDER_DOCS_URLS: Record<string, string> = {
  openai: "https://platform.openai.com/docs/guides/text-to-speech",
  azure: "https://learn.microsoft.com/en-us/azure/ai-services/speech-service/",
  elevenlabs: "https://elevenlabs.io/docs",
};

export const PROVIDER_VOICE_DOCS_URLS: Record<
  string,
  { url: string; label: string }
> = {
  openai: {
    url: "https://platform.openai.com/docs/guides/text-to-speech#voice-options",
    label: "OpenAI",
  },
  azure: {
    url: "https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support?tabs=tts",
    label: "Azure",
  },
  elevenlabs: {
    url: "https://elevenlabs.io/docs/voices/premade-voices",
    label: "ElevenLabs",
  },
};

export const OPENAI_STT_MODELS = [{ id: "whisper-1", name: "Whisper v1" }];

export const OPENAI_TTS_MODELS = [
  { id: "tts-1", name: "TTS-1" },
  { id: "tts-1-hd", name: "TTS-1 HD" },
];

/** Map card-level model IDs to actual API model IDs.
 *  IDs not in this map are used as-is (card ID = API ID). */
export const MODEL_ID_MAP: Record<string, string> = {
  whisper: "whisper-1",
};

/** Resolve a card-level model ID to the actual API model ID. */
export function resolveModelId(cardId: string): string {
  return MODEL_ID_MAP[cardId] ?? cardId;
}
