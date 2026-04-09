import type { IconFunctionComponent } from "@opal/types";
import { SvgCpu, SvgMicrophone, SvgPlug, SvgServer } from "@opal/icons";
import {
  SvgBifrost,
  SvgOpenai,
  SvgClaude,
  SvgOllama,
  SvgAws,
  SvgOpenrouter,
  SvgAzure,
  SvgGemini,
  SvgLitellm,
  SvgLmStudio,
} from "@opal/logos";
import {
  AzureIcon,
  ElevenLabsIcon,
  OpenAIIcon,
} from "@/components/icons/icons";
import { LLMProviderFormProps, LLMProviderName } from "@/interfaces/llm";
import type { LLMProviderView } from "@/interfaces/llm";
import OpenAIModal from "@/sections/modals/llmConfig/OpenAIModal";
import AnthropicModal from "@/sections/modals/llmConfig/AnthropicModal";
import OllamaModal from "@/sections/modals/llmConfig/OllamaModal";
import AzureModal from "@/sections/modals/llmConfig/AzureModal";
import BedrockModal from "@/sections/modals/llmConfig/BedrockModal";
import VertexAIModal from "@/sections/modals/llmConfig/VertexAIModal";
import OpenRouterModal from "@/sections/modals/llmConfig/OpenRouterModal";
import CustomModal from "@/sections/modals/llmConfig/CustomModal";
import LMStudioModal from "@/sections/modals/llmConfig/LMStudioModal";
import LiteLLMProxyModal from "@/sections/modals/llmConfig/LiteLLMProxyModal";
import BifrostModal from "@/sections/modals/llmConfig/BifrostModal";
import OpenAICompatibleModal from "@/sections/modals/llmConfig/OpenAICompatibleModal";

// ─── Text (LLM) providers ────────────────────────────────────────────────────

export interface LLMProviderEntry {
  icon: IconFunctionComponent;
  productName: string;
  companyName: string;
  Modal: React.ComponentType<LLMProviderFormProps>;
}

const LLM_PROVIDERS: Record<string, LLMProviderEntry> = {
  [LLMProviderName.OPENAI]: {
    icon: SvgOpenai,
    productName: "GPT",
    companyName: "OpenAI",
    Modal: OpenAIModal,
  },
  [LLMProviderName.ANTHROPIC]: {
    icon: SvgClaude,
    productName: "Claude",
    companyName: "Anthropic",
    Modal: AnthropicModal,
  },
  [LLMProviderName.VERTEX_AI]: {
    icon: SvgGemini,
    productName: "Gemini",
    companyName: "Google Cloud Vertex AI",
    Modal: VertexAIModal,
  },
  [LLMProviderName.BEDROCK]: {
    icon: SvgAws,
    productName: "Amazon Bedrock",
    companyName: "AWS",
    Modal: BedrockModal,
  },
  [LLMProviderName.AZURE]: {
    icon: SvgAzure,
    productName: "Azure OpenAI",
    companyName: "Microsoft Azure",
    Modal: AzureModal,
  },
  [LLMProviderName.LITELLM]: {
    icon: SvgLitellm,
    productName: "LiteLLM",
    companyName: "LiteLLM",
    Modal: CustomModal,
  },
  [LLMProviderName.LITELLM_PROXY]: {
    icon: SvgLitellm,
    productName: "LiteLLM Proxy",
    companyName: "LiteLLM Proxy",
    Modal: LiteLLMProxyModal,
  },
  [LLMProviderName.OLLAMA_CHAT]: {
    icon: SvgOllama,
    productName: "Ollama",
    companyName: "Ollama",
    Modal: OllamaModal,
  },
  [LLMProviderName.OPENROUTER]: {
    icon: SvgOpenrouter,
    productName: "OpenRouter",
    companyName: "OpenRouter",
    Modal: OpenRouterModal,
  },
  [LLMProviderName.LM_STUDIO]: {
    icon: SvgLmStudio,
    productName: "LM Studio",
    companyName: "LM Studio",
    Modal: LMStudioModal,
  },
  [LLMProviderName.BIFROST]: {
    icon: SvgBifrost,
    productName: "Bifrost",
    companyName: "Bifrost",
    Modal: BifrostModal,
  },
  [LLMProviderName.OPENAI_COMPATIBLE]: {
    icon: SvgPlug,
    productName: "OpenAI-Compatible",
    companyName: "OpenAI-Compatible",
    Modal: OpenAICompatibleModal,
  },
  [LLMProviderName.CUSTOM]: {
    icon: SvgServer,
    productName: "Custom Models",
    companyName: "models from other LiteLLM-compatible providers",
    Modal: CustomModal,
  },
};

const DEFAULT_LLM_ENTRY: LLMProviderEntry = {
  icon: SvgCpu,
  productName: "",
  companyName: "",
  Modal: CustomModal,
};

// Providers that don't use custom_config themselves — if custom_config is
// present it means the provider was originally created via CustomModal.
const CUSTOM_CONFIG_OVERRIDES = new Set<string>([
  LLMProviderName.OPENAI,
  LLMProviderName.ANTHROPIC,
  LLMProviderName.AZURE,
  LLMProviderName.OPENROUTER,
]);

export function getLLMProvider(
  providerName: string,
  existingProvider?: LLMProviderView
): LLMProviderEntry {
  const entry = LLM_PROVIDERS[providerName] ?? {
    ...DEFAULT_LLM_ENTRY,
    productName: providerName,
    companyName: providerName,
  };

  if (
    existingProvider?.custom_config != null &&
    CUSTOM_CONFIG_OVERRIDES.has(providerName)
  ) {
    return { ...entry, Modal: CustomModal };
  }

  return entry;
}

// ─── Voice providers ─────────────────────────────────────────────────────────

export interface VoiceProviderEntry {
  icon: IconFunctionComponent;
  displayName: string;
}

const VOICE_PROVIDERS: Record<string, VoiceProviderEntry> = {
  openai: {
    icon: OpenAIIcon,
    displayName: "OpenAI",
  },
  azure: {
    icon: AzureIcon,
    displayName: "Azure",
  },
  elevenlabs: {
    icon: ElevenLabsIcon,
    displayName: "ElevenLabs",
  },
};

const DEFAULT_VOICE_ENTRY: VoiceProviderEntry = {
  icon: SvgMicrophone,
  displayName: "",
};

export function getVoiceProvider(providerType: string): VoiceProviderEntry {
  return (
    VOICE_PROVIDERS[providerType] ?? {
      ...DEFAULT_VOICE_ENTRY,
      displayName: providerType,
    }
  );
}
