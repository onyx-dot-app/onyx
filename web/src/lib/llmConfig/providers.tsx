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
import type { LLMProviderView } from "@/interfaces/llm";

// ---------------------------------------------------------------------------
// Aggregator providers (host models from multiple vendors)
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Unified provider registry (icon + product name + display name + modal)
// ---------------------------------------------------------------------------

interface ProviderEntry {
  icon: IconFunctionComponent;
  productName: string;
  displayName: string;
  Modal: React.ComponentType<LLMProviderFormProps>;
}

const PROVIDER_REGISTRY: Record<string, ProviderEntry> = {
  [LLMProviderName.OPENAI]: {
    icon: SvgOpenai,
    productName: "GPT",
    displayName: "OpenAI",
    Modal: OpenAIModal,
  },
  [LLMProviderName.ANTHROPIC]: {
    icon: SvgClaude,
    productName: "Claude",
    displayName: "Anthropic",
    Modal: AnthropicModal,
  },
  [LLMProviderName.VERTEX_AI]: {
    icon: SvgGemini,
    productName: "Gemini",
    displayName: "Google Cloud Vertex AI",
    Modal: VertexAIModal,
  },
  [LLMProviderName.BEDROCK]: {
    icon: SvgAws,
    productName: "Amazon Bedrock",
    displayName: "AWS",
    Modal: BedrockModal,
  },
  [LLMProviderName.AZURE]: {
    icon: SvgAzure,
    productName: "Azure OpenAI",
    displayName: "Microsoft Azure",
    Modal: AzureModal,
  },
  [LLMProviderName.LITELLM]: {
    icon: SvgLitellm,
    productName: "LiteLLM",
    displayName: "LiteLLM",
    Modal: CustomModal,
  },
  [LLMProviderName.LITELLM_PROXY]: {
    icon: SvgLitellm,
    productName: "LiteLLM Proxy",
    displayName: "LiteLLM Proxy",
    Modal: LiteLLMProxyModal,
  },
  [LLMProviderName.OLLAMA_CHAT]: {
    icon: SvgOllama,
    productName: "Ollama",
    displayName: "Ollama",
    Modal: OllamaModal,
  },
  [LLMProviderName.OPENROUTER]: {
    icon: SvgOpenrouter,
    productName: "OpenRouter",
    displayName: "OpenRouter",
    Modal: OpenRouterModal,
  },
  [LLMProviderName.LM_STUDIO]: {
    icon: SvgLmStudio,
    productName: "LM Studio",
    displayName: "LM Studio",
    Modal: LMStudioModal,
  },
  [LLMProviderName.BIFROST]: {
    icon: SvgBifrost,
    productName: "Bifrost",
    displayName: "Bifrost",
    Modal: BifrostModal,
  },
  [LLMProviderName.OPENAI_COMPATIBLE]: {
    icon: SvgPlug,
    productName: "OpenAI-Compatible",
    displayName: "OpenAI-Compatible",
    Modal: OpenAICompatibleModal,
  },
  [LLMProviderName.CUSTOM]: {
    icon: SvgServer,
    productName: "Custom Models",
    displayName: "models from other LiteLLM-compatible providers",
    Modal: CustomModal,
  },
};

// ---------------------------------------------------------------------------
// Public accessors
// ---------------------------------------------------------------------------

export function getProviderProductName(providerName: string): string {
  return PROVIDER_REGISTRY[providerName]?.productName ?? providerName;
}

export function getProviderDisplayName(providerName: string): string {
  return PROVIDER_REGISTRY[providerName]?.displayName ?? providerName;
}

export function getProviderIcon(providerName: string): IconFunctionComponent {
  return PROVIDER_REGISTRY[providerName]?.icon ?? SvgCpu;
}

export function getProviderModal(
  providerName: string
): React.ComponentType<LLMProviderFormProps> | undefined {
  return PROVIDER_REGISTRY[providerName]?.Modal;
}

// ---------------------------------------------------------------------------
// Modal for *existing* (already-configured) providers
// ---------------------------------------------------------------------------

export function getModalForExistingProvider(
  provider: LLMProviderView,
  onOpenChange?: (open: boolean) => void,
  defaultModelName?: string
) {
  const props = {
    existingLlmProvider: provider,
    onOpenChange,
    defaultModelName,
  };

  const hasCustomConfig = provider.custom_config != null;

  switch (provider.provider) {
    // These providers don't use custom_config themselves, so a non-null
    // custom_config means the provider was created via CustomModal.
    case LLMProviderName.OPENAI:
      return hasCustomConfig ? (
        <CustomModal {...props} />
      ) : (
        <OpenAIModal {...props} />
      );
    case LLMProviderName.ANTHROPIC:
      return hasCustomConfig ? (
        <CustomModal {...props} />
      ) : (
        <AnthropicModal {...props} />
      );
    case LLMProviderName.AZURE:
      return hasCustomConfig ? (
        <CustomModal {...props} />
      ) : (
        <AzureModal {...props} />
      );
    case LLMProviderName.OPENROUTER:
      return hasCustomConfig ? (
        <CustomModal {...props} />
      ) : (
        <OpenRouterModal {...props} />
      );

    // These providers legitimately store settings in custom_config,
    // so always use their dedicated modals.
    case LLMProviderName.OLLAMA_CHAT:
      return <OllamaModal {...props} />;
    case LLMProviderName.VERTEX_AI:
      return <VertexAIModal {...props} />;
    case LLMProviderName.BEDROCK:
      return <BedrockModal {...props} />;
    case LLMProviderName.LM_STUDIO:
      return <LMStudioModal {...props} />;
    case LLMProviderName.LITELLM_PROXY:
      return <LiteLLMProxyModal {...props} />;
    case LLMProviderName.BIFROST:
      return <BifrostModal {...props} />;
    case LLMProviderName.OPENAI_COMPATIBLE:
      return <OpenAICompatibleModal {...props} />;
    default:
      return <CustomModal {...props} />;
  }
}

// ---------------------------------------------------------------------------
// Model-aware icon resolver (legacy icon set)
// ---------------------------------------------------------------------------

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
export const getModelIcon = (
  providerName: string,
  modelName?: string
): IconFunctionComponent => {
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
};
