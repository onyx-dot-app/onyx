import { JSX } from "react";
import {
  AnthropicIcon,
  AmazonIcon,
  AzureIcon,
  CPUIcon,
  MicrosoftIconSVG,
  MistralIcon,
  MetaIcon,
  GeminiIcon,
  IconProps,
  DeepseekIcon,
  OpenAISVG,
  QwenIcon,
  OllamaIcon,
  ZAIIcon,
} from "@/components/icons/icons";
import {
  OllamaModelResponse,
  OpenRouterModelResponse,
  BedrockModelResponse,
  ModelConfiguration,
  LLMProviderName,
  BedrockFetchParams,
  OllamaFetchParams,
  OpenRouterFetchParams,
} from "./interfaces";
import { SvgAws, SvgOpenrouter } from "@opal/icons";

// Aggregator providers that host models from multiple vendors
export const AGGREGATOR_PROVIDERS = new Set([
  "bedrock",
  "bedrock_converse",
  "openrouter",
  "ollama_chat",
  "vertex_ai",
]);

export const getProviderIcon = (
  providerName: string,
  modelName?: string
): (({ size, className }: IconProps) => JSX.Element) => {
  const iconMap: Record<
    string,
    ({ size, className }: IconProps) => JSX.Element
  > = {
    amazon: AmazonIcon,
    phi: MicrosoftIconSVG,
    mistral: MistralIcon,
    ministral: MistralIcon,
    llama: MetaIcon,
    ollama_chat: OllamaIcon,
    ollama: OllamaIcon,
    gemini: GeminiIcon,
    deepseek: DeepseekIcon,
    claude: AnthropicIcon,
    anthropic: AnthropicIcon,
    openai: OpenAISVG,
    // Azure OpenAI should display the Azure logo
    azure: AzureIcon,
    microsoft: MicrosoftIconSVG,
    meta: MetaIcon,
    google: GeminiIcon,
    qwen: QwenIcon,
    qwq: QwenIcon,
    zai: ZAIIcon,
    // Cloud providers - use AWS icon for Bedrock
    bedrock: SvgAws,
    bedrock_converse: SvgAws,
    openrouter: SvgOpenrouter,
    vertex_ai: GeminiIcon,
  };

  const lowerProviderName = providerName.toLowerCase();

  // For aggregator providers (bedrock, openrouter, vertex_ai), prioritize showing
  // the vendor icon based on model name (e.g., show Claude icon for Bedrock Claude models)
  if (AGGREGATOR_PROVIDERS.has(lowerProviderName) && modelName) {
    const lowerModelName = modelName.toLowerCase();
    for (const [key, icon] of Object.entries(iconMap)) {
      if (lowerModelName.includes(key)) {
        return icon;
      }
    }
  }

  // Check if provider name directly matches an icon
  if (lowerProviderName in iconMap) {
    const icon = iconMap[lowerProviderName];
    if (icon) {
      return icon;
    }
  }

  // For non-aggregator providers, check if model name contains any of the keys
  if (modelName) {
    const lowerModelName = modelName.toLowerCase();
    for (const [key, icon] of Object.entries(iconMap)) {
      if (lowerModelName.includes(key)) {
        return icon;
      }
    }
  }

  // Fallback to CPU icon if no matches
  return CPUIcon;
};

export const isAnthropic = (provider: string, modelName: string) =>
  provider === "anthropic" || modelName.toLowerCase().includes("claude");

/**
 * Fetches Bedrock models directly without any form state dependencies.
 * Uses snake_case params to match API structure.
 */
export const fetchBedrockModels = async (
  params: BedrockFetchParams
): Promise<{ models: ModelConfiguration[]; error?: string }> => {
  if (!params.aws_region_name) {
    return { models: [], error: "AWS region is required" };
  }

  try {
    const response = await fetch("/api/admin/llm/bedrock/available-models", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        aws_region_name: params.aws_region_name,
        aws_access_key_id: params.aws_access_key_id,
        aws_secret_access_key: params.aws_secret_access_key,
        aws_bearer_token_bedrock: params.aws_bearer_token_bedrock,
        provider_name: params.provider_name,
      }),
    });

    if (!response.ok) {
      let errorMessage = "Failed to fetch models";
      try {
        const errorData = await response.json();
        errorMessage = errorData.detail || errorMessage;
      } catch {
        // ignore JSON parsing errors
      }
      return { models: [], error: errorMessage };
    }

    const data: BedrockModelResponse[] = await response.json();
    const models: ModelConfiguration[] = data.map((modelData) => ({
      name: modelData.name,
      display_name: modelData.display_name,
      is_visible: false,
      max_input_tokens: modelData.max_input_tokens,
      supports_image_input: modelData.supports_image_input,
    }));

    return { models };
  } catch (error) {
    const errorMessage =
      error instanceof Error ? error.message : "Unknown error";
    return { models: [], error: errorMessage };
  }
};

/**
 * Fetches Ollama models directly without any form state dependencies.
 * Uses snake_case params to match API structure.
 */
export const fetchOllamaModels = async (
  params: OllamaFetchParams
): Promise<{ models: ModelConfiguration[]; error?: string }> => {
  const apiBase = params.api_base;
  if (!apiBase) {
    return { models: [], error: "API Base is required" };
  }

  try {
    const response = await fetch("/api/admin/llm/ollama/available-models", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        api_base: apiBase,
        provider_name: params.provider_name,
      }),
    });

    if (!response.ok) {
      let errorMessage = "Failed to fetch models";
      try {
        const errorData = await response.json();
        errorMessage = errorData.detail || errorMessage;
      } catch {
        // ignore JSON parsing errors
      }
      return { models: [], error: errorMessage };
    }

    const data: OllamaModelResponse[] = await response.json();
    const models: ModelConfiguration[] = data.map((modelData) => ({
      name: modelData.name,
      display_name: modelData.display_name,
      is_visible: true,
      max_input_tokens: modelData.max_input_tokens,
      supports_image_input: modelData.supports_image_input,
    }));

    return { models };
  } catch (error) {
    const errorMessage =
      error instanceof Error ? error.message : "Unknown error";
    return { models: [], error: errorMessage };
  }
};

/**
 * Fetches OpenRouter models directly without any form state dependencies.
 * Uses snake_case params to match API structure.
 */
export const fetchOpenRouterModels = async (
  params: OpenRouterFetchParams
): Promise<{ models: ModelConfiguration[]; error?: string }> => {
  const apiBase = params.api_base;
  const apiKey = params.api_key;
  if (!apiBase) {
    return { models: [], error: "API Base is required" };
  }
  if (!apiKey) {
    return { models: [], error: "API Key is required" };
  }

  try {
    const response = await fetch("/api/admin/llm/openrouter/available-models", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        api_base: apiBase,
        api_key: apiKey,
        provider_name: params.provider_name,
      }),
    });

    if (!response.ok) {
      let errorMessage = "Failed to fetch models";
      try {
        const errorData = await response.json();
        errorMessage = errorData.detail || errorMessage;
      } catch {
        // ignore JSON parsing errors
      }
      return { models: [], error: errorMessage };
    }

    const data: OpenRouterModelResponse[] = await response.json();
    const models: ModelConfiguration[] = data.map((modelData) => ({
      name: modelData.name,
      display_name: modelData.display_name,
      is_visible: true,
      max_input_tokens: modelData.max_input_tokens,
      supports_image_input: modelData.supports_image_input,
    }));

    return { models };
  } catch (error) {
    const errorMessage =
      error instanceof Error ? error.message : "Unknown error";
    return { models: [], error: errorMessage };
  }
};

/**
 * Fetches models for a provider. Accepts form values directly and maps them
 * to the expected fetch params format internally.
 */
export const fetchModels = async (
  providerName: string,
  formValues: {
    api_base?: string;
    api_key?: string;
    name?: string;
    custom_config?: Record<string, string>;
    model_configurations?: ModelConfiguration[];
  }
) => {
  const customConfig = formValues.custom_config || {};

  switch (providerName) {
    case LLMProviderName.BEDROCK:
      return fetchBedrockModels({
        aws_region_name: customConfig.AWS_REGION_NAME || "",
        aws_access_key_id: customConfig.AWS_ACCESS_KEY_ID,
        aws_secret_access_key: customConfig.AWS_SECRET_ACCESS_KEY,
        aws_bearer_token_bedrock: customConfig.AWS_BEARER_TOKEN_BEDROCK,
        provider_name: formValues.name,
      });
    case LLMProviderName.OLLAMA_CHAT:
      return fetchOllamaModels({
        api_base: formValues.api_base,
        provider_name: formValues.name,
      });
    case LLMProviderName.OPENROUTER:
      return fetchOpenRouterModels({
        api_base: formValues.api_base,
        api_key: formValues.api_key,
        provider_name: formValues.name,
      });
    default:
      return { models: [], error: `Unknown provider: ${providerName}` };
  }
};

export function canProviderFetchModels(providerName?: string) {
  if (!providerName) return false;
  switch (providerName) {
    case LLMProviderName.BEDROCK:
    case LLMProviderName.OLLAMA_CHAT:
    case LLMProviderName.OPENROUTER:
      return true;
    default:
      return false;
  }
}
