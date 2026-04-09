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
import { LLMProviderName } from "@/interfaces/llm";

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

const PROVIDER_ICONS: Record<string, IconFunctionComponent> = {
  [LLMProviderName.OPENAI]: SvgOpenai,
  [LLMProviderName.ANTHROPIC]: SvgClaude,
  [LLMProviderName.VERTEX_AI]: SvgGemini,
  [LLMProviderName.BEDROCK]: SvgAws,
  [LLMProviderName.AZURE]: SvgAzure,
  [LLMProviderName.LITELLM]: SvgLitellm,
  [LLMProviderName.LITELLM_PROXY]: SvgLitellm,
  [LLMProviderName.OLLAMA_CHAT]: SvgOllama,
  [LLMProviderName.OPENROUTER]: SvgOpenrouter,
  [LLMProviderName.LM_STUDIO]: SvgLmStudio,
  [LLMProviderName.BIFROST]: SvgBifrost,
  [LLMProviderName.OPENAI_COMPATIBLE]: SvgPlug,

  // fallback
  [LLMProviderName.CUSTOM]: SvgServer,
};

const PROVIDER_PRODUCT_NAMES: Record<string, string> = {
  [LLMProviderName.OPENAI]: "GPT",
  [LLMProviderName.ANTHROPIC]: "Claude",
  [LLMProviderName.VERTEX_AI]: "Gemini",
  [LLMProviderName.BEDROCK]: "Amazon Bedrock",
  [LLMProviderName.AZURE]: "Azure OpenAI",
  [LLMProviderName.LITELLM]: "LiteLLM",
  [LLMProviderName.LITELLM_PROXY]: "LiteLLM Proxy",
  [LLMProviderName.OLLAMA_CHAT]: "Ollama",
  [LLMProviderName.OPENROUTER]: "OpenRouter",
  [LLMProviderName.LM_STUDIO]: "LM Studio",
  [LLMProviderName.BIFROST]: "Bifrost",
  [LLMProviderName.OPENAI_COMPATIBLE]: "OpenAI-Compatible",

  // fallback
  [LLMProviderName.CUSTOM]: "Custom Models",
};

const PROVIDER_DISPLAY_NAMES: Record<string, string> = {
  [LLMProviderName.OPENAI]: "OpenAI",
  [LLMProviderName.ANTHROPIC]: "Anthropic",
  [LLMProviderName.VERTEX_AI]: "Google Cloud Vertex AI",
  [LLMProviderName.BEDROCK]: "AWS",
  [LLMProviderName.AZURE]: "Microsoft Azure",
  [LLMProviderName.LITELLM]: "LiteLLM",
  [LLMProviderName.LITELLM_PROXY]: "LiteLLM Proxy",
  [LLMProviderName.OLLAMA_CHAT]: "Ollama",
  [LLMProviderName.OPENROUTER]: "OpenRouter",
  [LLMProviderName.LM_STUDIO]: "LM Studio",
  [LLMProviderName.BIFROST]: "Bifrost",
  [LLMProviderName.OPENAI_COMPATIBLE]: "OpenAI-Compatible",

  // fallback
  [LLMProviderName.CUSTOM]: "models from other LiteLLM-compatible providers",
};

export function getProviderProductName(providerName: string): string {
  return PROVIDER_PRODUCT_NAMES[providerName] ?? providerName;
}

export function getProviderDisplayName(providerName: string): string {
  return PROVIDER_DISPLAY_NAMES[providerName] ?? providerName;
}

export function getProviderIcon(providerName: string): IconFunctionComponent {
  return PROVIDER_ICONS[providerName] ?? SvgCpu;
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
