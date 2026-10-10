import type { IconFunctionComponent } from "@opal/types";
import { SvgCpu, SvgPlug, SvgServer } from "@opal/icons";
import {
  SvgBifrost,
  SvgOpenAI,
  SvgClaude,
  SvgOllama,
  SvgAWS,
  SvgOpenRouter,
  SvgAzure,
  SvgGemini,
  SvgLiteLLM,
  SvgLMStudio,
  SvgMicrosoft,
  SvgMistral,
  SvgDeepSeek,
  SvgQwen,
  SvgGoogle,
  SvgNebius,
  SvgPortkey,
  SvgAtlascloud,
  SvgVercel,
} from "@opal/logos";
import { ZAIIcon } from "@/components/icons/icons";
import { LLMProviderName } from "@/lib/languageModels/types";
import OpenAIModal from "@/sections/modals/languageModels/OpenAIModal";
import AnthropicModal from "@/sections/modals/languageModels/AnthropicModal";
import OllamaModal from "@/sections/modals/languageModels/OllamaModal";
import AzureModal from "@/sections/modals/languageModels/AzureModal";
import BedrockModal from "@/sections/modals/languageModels/BedrockModal";
import VertexAIModal from "@/sections/modals/languageModels/VertexAIModal";
import OpenRouterModal from "@/sections/modals/languageModels/OpenRouterModal";
import CustomModal from "@/sections/modals/languageModels/CustomModal";
import LMStudioModal from "@/sections/modals/languageModels/LMStudioModal";
import LiteLLMProxyModal from "@/sections/modals/languageModels/LiteLLMProxyModal";
import BifrostModal from "@/sections/modals/languageModels/BifrostModal";
import OpenAICompatibleModal from "@/sections/modals/languageModels/OpenAICompatibleModal";
import NebiusTokenfactoryModal from "@/sections/modals/languageModels/NebiusTokenfactoryModal";
import PortkeyModal from "@/sections/modals/languageModels/PortkeyModal";
import VercelAIGatewayModal from "@/sections/modals/languageModels/VercelAIGatewayModal";
import AtlasCloudModal from "@/sections/modals/languageModels/AtlasCloudModal";
import type { ProviderEntry } from "@/lib/languageModels/types";

// ─── Text (LLM) providers ────────────────────────────────────────────────────

export const PROVIDERS: Record<string, ProviderEntry> = {
  [LLMProviderName.OPENAI]: {
    icon: SvgOpenAI,
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
    icon: SvgAWS,
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
    icon: SvgLiteLLM,
    productName: "LiteLLM",
    companyName: "LiteLLM",
    Modal: CustomModal,
  },
  [LLMProviderName.LITELLM_PROXY]: {
    icon: SvgLiteLLM,
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
    icon: SvgOpenRouter,
    productName: "OpenRouter",
    companyName: "OpenRouter",
    Modal: OpenRouterModal,
  },
  [LLMProviderName.LM_STUDIO]: {
    icon: SvgLMStudio,
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
  [LLMProviderName.NEBIUS_TOKENFACTORY]: {
    icon: SvgNebius,
    productName: "Nebius TokenFactory",
    companyName: "Nebius",
    Modal: NebiusTokenfactoryModal,
  },
  [LLMProviderName.PORTKEY]: {
    icon: SvgPortkey,
    productName: "Portkey",
    companyName: "Portkey",
    Modal: PortkeyModal,
  },
  [LLMProviderName.VERCEL_AI_GATEWAY]: {
    icon: SvgVercel,
    productName: "Vercel AI Gateway",
    companyName: "Vercel",
    Modal: VercelAIGatewayModal,
  },
  [LLMProviderName.ATLASCLOUD]: {
    icon: SvgAtlascloud,
    productName: "Atlas Cloud",
    companyName: "Atlas Cloud",
    Modal: AtlasCloudModal,
  },
  [LLMProviderName.CUSTOM]: {
    icon: SvgServer,
    productName: "Custom Models",
    companyName: "models from other LiteLLM-compatible providers",
    Modal: CustomModal,
  },
};

export const DEFAULT_ENTRY: ProviderEntry = {
  icon: SvgCpu,
  productName: "",
  companyName: "",
  Modal: CustomModal,
};

// Providers that don't use custom_config themselves, so a non-empty
// custom_config means the provider was originally created via CustomModal.
export const CUSTOM_CONFIG_OVERRIDES = new Set<string>([
  LLMProviderName.OPENAI,
  LLMProviderName.ANTHROPIC,
  LLMProviderName.AZURE,
  LLMProviderName.OPENROUTER,
]);

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
  LLMProviderName.NEBIUS_TOKENFACTORY,
  LLMProviderName.PORTKEY,
  LLMProviderName.VERCEL_AI_GATEWAY,
  LLMProviderName.ATLASCLOUD,
  LLMProviderName.VERTEX_AI,
]);

// ─── Model icons ─────────────────────────────────────────────────────────────

export const MODEL_ICON_MAP: Record<string, IconFunctionComponent> = {
  [LLMProviderName.OPENAI]: SvgOpenAI,
  [LLMProviderName.ANTHROPIC]: SvgClaude,
  [LLMProviderName.OLLAMA_CHAT]: SvgOllama,
  [LLMProviderName.LM_STUDIO]: SvgLMStudio,
  [LLMProviderName.OPENROUTER]: SvgOpenRouter,
  [LLMProviderName.VERTEX_AI]: SvgGemini,
  [LLMProviderName.BEDROCK]: SvgAWS,
  [LLMProviderName.LITELLM_PROXY]: SvgLiteLLM,
  [LLMProviderName.BIFROST]: SvgBifrost,
  [LLMProviderName.OPENAI_COMPATIBLE]: SvgPlug,
  [LLMProviderName.NEBIUS_TOKENFACTORY]: SvgNebius,
  [LLMProviderName.PORTKEY]: SvgPortkey,
  [LLMProviderName.VERCEL_AI_GATEWAY]: SvgVercel,
  [LLMProviderName.ATLASCLOUD]: SvgAtlascloud,

  amazon: SvgAWS,
  gpt: SvgOpenAI,
  phi: SvgMicrosoft,
  mistral: SvgMistral,
  ministral: SvgMistral,
  llama: SvgCpu,
  ollama: SvgOllama,
  gemini: SvgGemini,
  deepseek: SvgDeepSeek,
  claude: SvgClaude,
  azure: SvgAzure,
  microsoft: SvgMicrosoft,
  meta: SvgCpu,
  google: SvgGoogle,
  qwen: SvgQwen,
  qwq: SvgQwen,
  zai: ZAIIcon,
  bedrock_converse: SvgAWS,
};
