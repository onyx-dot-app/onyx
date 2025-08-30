import {
  AnthropicIcon,
  AmazonIcon,
  CPUIcon,
  MicrosoftIconSVG,
  MistralIcon,
  MetaIcon,
  GeminiIcon,
  IconProps,
  DeepseekIcon,
  OpenAISVG,
  XaiIcon,
  QwenIcon,
  CohereIcon,
} from "@/components/icons/icons";

const PROVIDER_PATTERNS: Record<string, string> = {
  amazon: "amazon",
  phi: "microsoft",
  mistral: "mistral",
  ministral: "mistral",
  grok: "xai",
  llama: "meta",
  gemini: "google",
  deepseek: "deepseek",
  claude: "anthropic",
  anthropic: "anthropic",
  openai: "openai",
  gpt: "openai",
  o1: "openai",
  o3: "openai",
  o4: "openai",
  microsoft: "microsoft",
  meta: "meta",
  google: "google",
  qwen: "qwen",
  qwq: "qwen",
  cohere: "cohere",
  command: "cohere",
};

export const getProviderType = (
  providerName: string,
  modelName?: string
): string => {
  const lowerProviderName = providerName.toLowerCase();

  // Special handling for OpenAI provider: try model-specific patterns first (as it could be a LiteLLM served model)
  if (lowerProviderName === "openai" && modelName) {
    const lowerModelName = modelName.toLowerCase();
    
    // Check model name patterns in priority order
    for (const [pattern, type] of Object.entries(PROVIDER_PATTERNS)) {
      if (pattern !== "openai" && lowerModelName.includes(pattern)) {
        return type;
      }
    }
  }

  // Standard provider name check
  if (lowerProviderName in PROVIDER_PATTERNS) {
    return PROVIDER_PATTERNS[lowerProviderName]!;
  }

  // Standard model name check for non-OpenAI providers
  if (modelName) {
    const lowerModelName = modelName.toLowerCase();
    for (const [pattern, type] of Object.entries(PROVIDER_PATTERNS)) {
      if (lowerModelName.includes(pattern)) {
        return type;
      }
    }
  }

  // Fallback
  return "other";
};

// Central mapping of provider types to icons
const PROVIDER_TYPE_TO_ICON: Record<string, ({ size, className }: IconProps) => JSX.Element> = {
  amazon: AmazonIcon,
  microsoft: MicrosoftIconSVG,
  mistral: MistralIcon,
  xai: XaiIcon,
  meta: MetaIcon,
  google: GeminiIcon,
  deepseek: DeepseekIcon,
  anthropic: AnthropicIcon,
  openai: OpenAISVG,
  qwen: QwenIcon,
  cohere: CohereIcon,
  other: CPUIcon,
};

export const getProviderIcon = (
  providerName: string,
  modelName?: string
): (({ size, className }: IconProps) => JSX.Element) => {
  const providerType = getProviderType(providerName, modelName);
  return PROVIDER_TYPE_TO_ICON[providerType] || CPUIcon;
};

export const isAnthropic = (provider: string, modelName: string) =>
  provider === "anthropic" || modelName.toLowerCase().includes("claude");
