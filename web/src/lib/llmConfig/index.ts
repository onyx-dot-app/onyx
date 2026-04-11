import type { IconFunctionComponent } from "@opal/types";
import { SvgCpu, SvgPlug, SvgServer } from "@opal/icons";
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
  SvgMicrosoft,
  SvgMistral,
  SvgDeepseek,
  SvgQwen,
  SvgGoogle,
} from "@opal/logos";
import { ZAIIcon } from "@/components/icons/icons";
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

export interface ProviderEntry {
  icon: IconFunctionComponent;
  productName: string;
  companyName: string;
  Modal: React.ComponentType<LLMProviderFormProps>;
}

const PROVIDERS: Record<string, ProviderEntry> = {
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

const DEFAULT_ENTRY: ProviderEntry = {
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

export function getProvider(
  providerName: string,
  existingProvider?: LLMProviderView
): ProviderEntry {
  const entry = PROVIDERS[providerName] ?? {
    ...DEFAULT_ENTRY,
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

// ─── Aggregator providers ────────────────────────────────────────────────────
// Providers that host models from multiple vendors (e.g. Bedrock hosts Claude,
// Llama, etc.) Used by the model-icon resolver to prioritise vendor icons.

export const AGGREGATOR_PROVIDERS = new Set([
  LLMProviderName.BEDROCK,
  "bedrock_converse",
  LLMProviderName.OPENROUTER,
  LLMProviderName.OLLAMA_CHAT,
  LLMProviderName.LM_STUDIO,
  LLMProviderName.LITELLM_PROXY,
  LLMProviderName.BIFROST,
  LLMProviderName.OPENAI_COMPATIBLE,
  LLMProviderName.VERTEX_AI,
]);

// ─── Model-aware icon resolver ───────────────────────────────────────────────

const MODEL_ICON_MAP: Record<string, IconFunctionComponent> = {
  [LLMProviderName.OPENAI]: SvgOpenai,
  [LLMProviderName.ANTHROPIC]: SvgClaude,
  [LLMProviderName.OLLAMA_CHAT]: SvgOllama,
  [LLMProviderName.LM_STUDIO]: SvgLmStudio,
  [LLMProviderName.OPENROUTER]: SvgOpenrouter,
  [LLMProviderName.VERTEX_AI]: SvgGemini,
  [LLMProviderName.BEDROCK]: SvgAws,
  [LLMProviderName.LITELLM_PROXY]: SvgLitellm,
  [LLMProviderName.BIFROST]: SvgBifrost,
  [LLMProviderName.OPENAI_COMPATIBLE]: SvgPlug,

  amazon: SvgAws,
  phi: SvgMicrosoft,
  mistral: SvgMistral,
  ministral: SvgMistral,
  llama: SvgCpu,
  ollama: SvgOllama,
  gemini: SvgGemini,
  deepseek: SvgDeepseek,
  claude: SvgClaude,
  azure: SvgAzure,
  microsoft: SvgMicrosoft,
  meta: SvgCpu,
  google: SvgGoogle,
  qwen: SvgQwen,
  qwq: SvgQwen,
  zai: ZAIIcon,
  bedrock_converse: SvgAws,
};

/**
 * Model-aware icon resolver that checks both provider name and model name
 * to pick the most specific icon (e.g. Claude icon for a Bedrock Claude model).
 */
export function getModelIcon(
  providerName: string,
  modelName?: string
): IconFunctionComponent {
  const lowerProviderName = providerName.toLowerCase();

  // For aggregator providers, prioritise showing the vendor icon based on model name
  if (AGGREGATOR_PROVIDERS.has(lowerProviderName) && modelName) {
    const lowerModelName = modelName.toLowerCase();
    for (const [key, icon] of Object.entries(MODEL_ICON_MAP)) {
      if (lowerModelName.includes(key)) {
        return icon;
      }
    }
  }

  // Check if provider name directly matches an icon
  if (lowerProviderName in MODEL_ICON_MAP) {
    const icon = MODEL_ICON_MAP[lowerProviderName];
    if (icon) {
      return icon;
    }
  }

  // For non-aggregator providers, check if model name contains any of the keys
  if (modelName) {
    const lowerModelName = modelName.toLowerCase();
    for (const [key, icon] of Object.entries(MODEL_ICON_MAP)) {
      if (lowerModelName.includes(key)) {
        return icon;
      }
    }
  }

  // Fallback to CPU icon if no matches
  return SvgCpu;
}
