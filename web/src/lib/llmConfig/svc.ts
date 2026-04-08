/**
 * LLM action functions for mutations and model fetching.
 *
 * These are async functions for one-off actions that don't need SWR caching.
 *
 * Endpoints:
 * - /api/admin/llm/test/default - Test the default LLM provider connection
 * - /api/admin/llm/default - Set the default LLM model
 * - /api/admin/llm/provider/{id} - Delete an LLM provider
 * - /api/admin/llm/{provider}/available-models - Fetch available models for a provider
 */

import {
  LLM_ADMIN_URL,
  LLM_PROVIDERS_ADMIN_URL,
} from "@/lib/llmConfig/constants";
import {
  OllamaModelResponse,
  OpenRouterModelResponse,
  BedrockModelResponse,
  LMStudioModelResponse,
  LiteLLMProxyModelResponse,
  BifrostModelResponse,
  ModelConfiguration,
  LLMProviderName,
  BedrockFetchParams,
  OllamaFetchParams,
  LMStudioFetchParams,
  OpenRouterFetchParams,
  LiteLLMProxyFetchParams,
  BifrostFetchParams,
  OpenAICompatibleFetchParams,
  OpenAICompatibleModelResponse,
} from "@/interfaces/llm";

/**
 * Test the default LLM provider.
 * Returns true if the default provider is configured and working, false otherwise.
 */
export async function testDefaultProvider(): Promise<boolean> {
  try {
    const response = await fetch(`${LLM_ADMIN_URL}/test/default`, {
      method: "POST",
    });
    return response?.ok || false;
  } catch {
    return false;
  }
}

/**
 * Set the default LLM model.
 * @param providerId - The provider ID
 * @param modelName - The model name within that provider
 * @throws Error with the detail message from the API on failure
 */
export async function setDefaultLlmModel(
  providerId: number,
  modelName: string
): Promise<void> {
  const response = await fetch(`${LLM_ADMIN_URL}/default`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      provider_id: providerId,
      model_name: modelName,
    }),
  });

  if (!response.ok) {
    const errorMsg = (await response.json()).detail;
    throw new Error(errorMsg);
  }
}

/**
 * Delete an LLM provider.
 * @param providerId - The provider ID to delete
 * @throws Error with the detail message from the API on failure
 */
export async function deleteLlmProvider(providerId: number): Promise<void> {
  const response = await fetch(`${LLM_PROVIDERS_ADMIN_URL}/${providerId}`, {
    method: "DELETE",
  });

  if (!response.ok) {
    const errorMsg = (await response.json()).detail;
    throw new Error(errorMsg);
  }
}

// ---------------------------------------------------------------------------
// Aggregator providers & helpers
// ---------------------------------------------------------------------------

/** Aggregator providers that host models from multiple vendors. */
export const AGGREGATOR_PROVIDERS = new Set([
  "bedrock",
  "bedrock_converse",
  "openrouter",
  "ollama_chat",
  "lm_studio",
  "litellm_proxy",
  "bifrost",
  "openai_compatible",
  "vertex_ai",
]);

export const isAnthropic = (provider: string, modelName?: string) =>
  provider === LLMProviderName.ANTHROPIC ||
  !!modelName?.toLowerCase().includes("claude");

// ---------------------------------------------------------------------------
// Model fetching
// ---------------------------------------------------------------------------

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
        errorMessage = errorData.detail || errorData.message || errorMessage;
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
      supports_reasoning: false,
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
      signal: params.signal,
    });

    if (!response.ok) {
      let errorMessage = "Failed to fetch models";
      try {
        const errorData = await response.json();
        errorMessage = errorData.detail || errorData.message || errorMessage;
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
      supports_reasoning: false,
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
        errorMessage = errorData.detail || errorData.message || errorMessage;
      } catch (jsonError) {
        console.warn(
          "Failed to parse OpenRouter model fetch error response",
          jsonError
        );
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
      supports_reasoning: false,
    }));

    return { models };
  } catch (error) {
    const errorMessage =
      error instanceof Error ? error.message : "Unknown error";
    return { models: [], error: errorMessage };
  }
};

/**
 * Fetches LM Studio models directly without any form state dependencies.
 * Uses snake_case params to match API structure.
 */
export const fetchLMStudioModels = async (
  params: LMStudioFetchParams
): Promise<{ models: ModelConfiguration[]; error?: string }> => {
  const apiBase = params.api_base;
  if (!apiBase) {
    return { models: [], error: "API Base is required" };
  }

  try {
    const response = await fetch("/api/admin/llm/lm-studio/available-models", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        api_base: apiBase,
        api_key: params.api_key,
        api_key_changed: params.api_key_changed ?? false,
        provider_name: params.provider_name,
      }),
      signal: params.signal,
    });

    if (!response.ok) {
      let errorMessage = "Failed to fetch models";
      try {
        const errorData = await response.json();
        errorMessage = errorData.detail || errorData.message || errorMessage;
      } catch (jsonError) {
        console.warn(
          "Failed to parse LM Studio model fetch error response",
          jsonError
        );
      }
      return { models: [], error: errorMessage };
    }

    const data: LMStudioModelResponse[] = await response.json();
    const models: ModelConfiguration[] = data.map((modelData) => ({
      name: modelData.name,
      display_name: modelData.display_name,
      is_visible: true,
      max_input_tokens: modelData.max_input_tokens,
      supports_image_input: modelData.supports_image_input,
      supports_reasoning: modelData.supports_reasoning,
    }));

    return { models };
  } catch (error) {
    const errorMessage =
      error instanceof Error ? error.message : "Unknown error";
    return { models: [], error: errorMessage };
  }
};

/**
 * Fetches Bifrost models directly without any form state dependencies.
 * Uses snake_case params to match API structure.
 */
export const fetchBifrostModels = async (
  params: BifrostFetchParams
): Promise<{ models: ModelConfiguration[]; error?: string }> => {
  const apiBase = params.api_base;
  if (!apiBase) {
    return { models: [], error: "API Base is required" };
  }

  try {
    const response = await fetch("/api/admin/llm/bifrost/available-models", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        api_base: apiBase,
        api_key: params.api_key,
        provider_name: params.provider_name,
      }),
      signal: params.signal,
    });

    if (!response.ok) {
      let errorMessage = "Failed to fetch models";
      try {
        const errorData = await response.json();
        errorMessage = errorData.detail || errorData.message || errorMessage;
      } catch (jsonError) {
        console.warn(
          "Failed to parse Bifrost model fetch error response",
          jsonError
        );
      }
      return { models: [], error: errorMessage };
    }

    const data: BifrostModelResponse[] = await response.json();
    const models: ModelConfiguration[] = data.map((modelData) => ({
      name: modelData.name,
      display_name: modelData.display_name,
      is_visible: true,
      max_input_tokens: modelData.max_input_tokens,
      supports_image_input: modelData.supports_image_input,
      supports_reasoning: modelData.supports_reasoning,
    }));

    return { models };
  } catch (error) {
    const errorMessage =
      error instanceof Error ? error.message : "Unknown error";
    return { models: [], error: errorMessage };
  }
};

/**
 * Fetches models from a generic OpenAI-compatible server.
 * Uses snake_case params to match API structure.
 */
export const fetchOpenAICompatibleModels = async (
  params: OpenAICompatibleFetchParams
): Promise<{ models: ModelConfiguration[]; error?: string }> => {
  const apiBase = params.api_base;
  if (!apiBase) {
    return { models: [], error: "API Base is required" };
  }

  try {
    const response = await fetch(
      "/api/admin/llm/openai-compatible/available-models",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          api_base: apiBase,
          api_key: params.api_key,
          provider_name: params.provider_name,
        }),
        signal: params.signal,
      }
    );

    if (!response.ok) {
      let errorMessage = "Failed to fetch models";
      try {
        const errorData = await response.json();
        errorMessage = errorData.detail || errorData.message || errorMessage;
      } catch {
        // ignore JSON parsing errors
      }
      return { models: [], error: errorMessage };
    }

    const data: OpenAICompatibleModelResponse[] = await response.json();
    const models: ModelConfiguration[] = data.map((modelData) => ({
      name: modelData.name,
      display_name: modelData.display_name,
      is_visible: true,
      max_input_tokens: modelData.max_input_tokens,
      supports_image_input: modelData.supports_image_input,
      supports_reasoning: modelData.supports_reasoning,
    }));

    return { models };
  } catch (error) {
    const errorMessage =
      error instanceof Error ? error.message : "Unknown error";
    return { models: [], error: errorMessage };
  }
};

/**
 * Fetches LiteLLM Proxy models directly without any form state dependencies.
 * Uses snake_case params to match API structure.
 */
export const fetchLiteLLMProxyModels = async (
  params: LiteLLMProxyFetchParams
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
    const response = await fetch("/api/admin/llm/litellm/available-models", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        api_base: apiBase,
        api_key: apiKey,
        provider_name: params.provider_name,
      }),
      signal: params.signal,
    });

    if (!response.ok) {
      let errorMessage = "Failed to fetch models";
      try {
        const errorData = await response.json();
        errorMessage = errorData.detail || errorData.message || errorMessage;
      } catch {
        // ignore JSON parsing errors
      }
      return { models: [], error: errorMessage };
    }

    const data: LiteLLMProxyModelResponse[] = await response.json();
    const models: ModelConfiguration[] = data.map((modelData) => ({
      name: modelData.model_name,
      display_name: modelData.model_name,
      is_visible: true,
      max_input_tokens: null,
      supports_image_input: false,
      supports_reasoning: false,
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
    api_key_changed?: boolean;
    name?: string;
    custom_config?: Record<string, string>;
    model_configurations?: ModelConfiguration[];
  },
  signal?: AbortSignal
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
        signal,
      });
    case LLMProviderName.LM_STUDIO:
      return fetchLMStudioModels({
        api_base: formValues.api_base,
        api_key: formValues.custom_config?.LM_STUDIO_API_KEY,
        api_key_changed: formValues.api_key_changed ?? false,
        provider_name: formValues.name,
        signal,
      });
    case LLMProviderName.OPENROUTER:
      return fetchOpenRouterModels({
        api_base: formValues.api_base,
        api_key: formValues.api_key,
        provider_name: formValues.name,
      });
    case LLMProviderName.LITELLM_PROXY:
      return fetchLiteLLMProxyModels({
        api_base: formValues.api_base,
        api_key: formValues.api_key,
        provider_name: formValues.name,
        signal,
      });
    case LLMProviderName.BIFROST:
      return fetchBifrostModels({
        api_base: formValues.api_base,
        api_key: formValues.api_key,
        provider_name: formValues.name,
        signal,
      });
    case LLMProviderName.OPENAI_COMPATIBLE:
      return fetchOpenAICompatibleModels({
        api_base: formValues.api_base,
        api_key: formValues.api_key,
        provider_name: formValues.name,
        signal,
      });
    default:
      return { models: [], error: `Unknown provider: ${providerName}` };
  }
};
