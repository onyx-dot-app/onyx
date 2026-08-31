import { SvgAzure, SvgElevenLabs, SvgOpenai } from "@opal/logos";
import { SvgMicrophone, SvgServer } from "@opal/icons";
import type { IconProps } from "@opal/types";

/** Whether the provider is being configured for speech-to-text or text-to-speech. */
export type ProviderMode = "stt" | "tts";

/**
 * Strip markdown formatting so TTS engines don't read syntax (e.g. "#", "*")
 * aloud literally. Shared by voice-mode auto-playback and the manual "Read
 * aloud" button so both paths sound identical.
 */
export function stripMarkdownForTTS(text: string): string {
  return text
    .replace(/\*\*/g, "") // Remove bold markers
    .replace(/\*/g, "") // Remove italic markers
    .replace(/__/g, "") // Remove underscore-bold markers
    .replace(/_/g, "") // Remove underscore-italic markers
    .replace(/`{1,3}/g, "") // Remove code markers
    .replace(/^#{1,6}\s*/gm, "") // Remove headers (line-start only)
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1") // Convert links to just text
    .replace(/\n+/g, " ") // Replace newlines with spaces
    .replace(/\s+/g, " ") // Normalize whitespace
    .trim();
}

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
  /** Set if the provider supports configurable STT languages; renders the Spoken Languages field. */
  sttLanguages?: { docsUrl: string };
  /** Local OpenAI-compatible servers can use dummy or empty API keys. */
  apiKeyOptional?: boolean;
}

/** Locale shape for STT languages; mirrors AZURE_LOCALE_PATTERN in backend/onyx/voice/providers/azure.py. */
export const STT_LOCALE_PATTERN = /^[A-Za-z]{2,3}(-[A-Za-z]{2,8}){1,2}$/;

/** Azure's candidate caps for STT language auto-detect: continuous LID (cloud) vs at-start (self-hosted). */
export const MAX_STT_LANGUAGES = 10;
export const MAX_AT_START_STT_LANGUAGES = 4;

const AZURE_CLOUD_HOST_SUFFIXES = [
  ".speech.microsoft.com",
  ".api.cognitive.microsoft.com",
  ".cognitiveservices.azure.com",
];

/** Mirrors _is_azure_cloud_url in backend/onyx/voice/providers/azure.py. */
function isAzureCloudUrl(uri: string): boolean {
  try {
    const hostname = new URL(uri).hostname.toLowerCase();
    return AZURE_CLOUD_HOST_SUFFIXES.some((suffix) =>
      hostname.endsWith(suffix)
    );
  } catch {
    return false;
  }
}

/** Language cap for the endpoint the admin entered: self-hosted endpoints use at-start detection. */
export function maxSttLanguagesForTargetUri(targetUri: string): number {
  return !targetUri || isAzureCloudUrl(targetUri)
    ? MAX_STT_LANGUAGES
    : MAX_AT_START_STT_LANGUAGES;
}

/** Splits comma-separated locale input into trimmed entries. */
export function parseSttLanguages(value: string): string[] {
  return value
    .split(",")
    .map((lang) => lang.trim())
    .filter(Boolean);
}

/** Renders stored stt_languages config as the form's comma-separated input value. */
export function sttLanguagesToInput(raw: unknown): string {
  return Array.isArray(raw)
    ? raw.filter((v): v is string => typeof v === "string").join(", ")
    : "";
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
    sttLanguages: {
      docsUrl:
        "https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support?tabs=stt",
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
  local_openai: {
    label: "Local OpenAI-compatible",
    icon: SvgServer,
    docsUrl: "https://github.com/remsky/Kokoro-FastAPI",
    voiceDocsUrl: {
      url: "https://github.com/remsky/Kokoro-FastAPI",
      label: "Kokoro",
    },
    sttModels: [{ id: "mlx-whisper", name: "MLX Whisper" }],
    ttsModels: [{ id: "kokoro", name: "Kokoro" }],
    apiKeyOptional: true,
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
