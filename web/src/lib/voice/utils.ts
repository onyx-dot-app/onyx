import { SvgAzure, SvgElevenLabs, SvgOpenai } from "@opal/logos";
import { SvgMicrophone } from "@opal/icons";
import type { IconProps } from "@opal/types";

/** Supported first-party voice provider identifiers. */
export type VoiceProviderType = "openai" | "azure" | "elevenlabs";

/** Whether the provider is being configured for speech-to-text or text-to-speech. */
export type ProviderMode = "stt" | "tts";

/** Static display details for each voice provider. Fallback to `SvgMicrophone` / the raw provider_type string for unknown providers. */
export const VOICE_PROVIDER_DETAILS: Record<
  string,
  { label: string; icon: React.FunctionComponent<IconProps> }
> = {
  openai: { label: "OpenAI", icon: SvgOpenai },
  azure: { label: "Azure Speech Services", icon: SvgAzure },
  elevenlabs: { label: "ElevenLabs", icon: SvgElevenLabs },
};

/** Fallback icon for provider types not in VOICE_PROVIDER_DETAILS. */
export const VOICE_PROVIDER_FALLBACK_ICON = SvgMicrophone;

/** Links to each provider's API key management page. */
export const PROVIDER_API_KEY_URLS: Record<string, string> = {
  openai: "https://platform.openai.com/api-keys",
  azure: "https://portal.azure.com/",
  elevenlabs: "https://elevenlabs.io/app/settings/api-keys",
};

/** Links to each provider's general documentation. */
export const PROVIDER_DOCS_URLS: Record<string, string> = {
  openai: "https://platform.openai.com/docs/guides/text-to-speech",
  azure: "https://learn.microsoft.com/en-us/azure/ai-services/speech-service/",
  elevenlabs: "https://elevenlabs.io/docs",
};

/** Links to each provider's voice/language reference docs, used in the TTS voice picker description. */
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

/** Available OpenAI speech-to-text models. */
export const OPENAI_STT_MODELS = [{ id: "whisper-1", name: "Whisper v1" }];

/** Available OpenAI text-to-speech models. */
export const OPENAI_TTS_MODELS = [
  { id: "tts-1", name: "TTS-1" },
  { id: "tts-1-hd", name: "TTS-1 HD" },
];

/** Maps card-level model IDs to actual API model IDs. IDs absent from this map are used as-is. */
export const MODEL_ID_MAP: Record<string, string> = {
  whisper: "whisper-1",
};

/** Resolves a card-level model ID to the API model ID expected by the backend. */
export function resolveModelId(cardId: string): string {
  return MODEL_ID_MAP[cardId] ?? cardId;
}
