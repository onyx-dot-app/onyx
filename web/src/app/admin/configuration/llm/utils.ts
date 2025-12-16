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
  WellKnownLLMProviderDescriptor,
  LLMProviderView,
  DynamicProviderConfig,
  OllamaModelResponse,
  OpenRouterModelResponse,
  BedrockModelResponse,
  ModelConfiguration,
} from "./interfaces";
import { PopupSpec } from "@/components/admin/connectors/Popup";
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

// Static provider configs - these use the models from the descriptor (litellm)
// without making an API call. Used for OpenAI, Anthropic, Vertex AI, etc.
const createStaticProviderConfig = (
  providerDisplayName: string
): DynamicProviderConfig<ModelConfiguration[], ModelConfiguration> => ({
  endpoint: "", // Not used for static providers
  isDisabled: () => false,
  disabledReason: "",
  buildRequestBody: () => ({}),
  // For static providers, we pass through the descriptor's models directly
  processResponse: (models) => models,
  getModelNames: (models) => models.map((m) => m.name),
  successMessage: (count: number) =>
    `Refreshed ${count} available ${providerDisplayName} models.`,
  // Flag to indicate this is a static provider (uses descriptor models)
  isStatic: true,
});

export const dynamicProviderConfigs: Record<
  string,
  DynamicProviderConfig<any, ModelConfiguration>
> = {
  // Static providers - use models from litellm via the descriptor
  openai: createStaticProviderConfig("OpenAI"),
  anthropic: createStaticProviderConfig("Anthropic"),
  vertex_ai: createStaticProviderConfig("Vertex AI"),

  // Dynamic providers - fetch models from external APIs
  bedrock: {
    endpoint: "/api/admin/llm/bedrock/available-models",
    isDisabled: (values) => !values.custom_config?.AWS_REGION_NAME,
    disabledReason: "AWS region is required to fetch Bedrock models",
    buildRequestBody: ({ values, existingLlmProvider }) => ({
      aws_region_name: values.custom_config?.AWS_REGION_NAME,
      aws_access_key_id: values.custom_config?.AWS_ACCESS_KEY_ID,
      aws_secret_access_key: values.custom_config?.AWS_SECRET_ACCESS_KEY,
      aws_bearer_token_bedrock: values.custom_config?.AWS_BEARER_TOKEN_BEDROCK,
      provider_name: existingLlmProvider?.name,
    }),
    processResponse: (data: BedrockModelResponse[], llmProviderDescriptor) =>
      data.map((modelData) => {
        const existingConfig = llmProviderDescriptor.model_configurations.find(
          (config) => config.name === modelData.name
        );
        return {
          name: modelData.name,
          display_name: modelData.display_name,
          is_visible: existingConfig?.is_visible ?? false,
          max_input_tokens: modelData.max_input_tokens,
          supports_image_input: modelData.supports_image_input,
        };
      }),
    getModelNames: (data: BedrockModelResponse[]) =>
      data.map((model) => model.name),
    successMessage: (count: number) =>
      `Successfully fetched ${count} models for the selected region (including cross-region inference models).`,
  },
  ollama_chat: {
    endpoint: "/api/admin/llm/ollama/available-models",
    isDisabled: (values) => !values.api_base,
    disabledReason: "API Base is required to fetch Ollama models",
    buildRequestBody: ({ values, existingLlmProvider }) => ({
      api_base: values.api_base,
      provider_name: existingLlmProvider?.name,
    }),
    processResponse: (data: OllamaModelResponse[], llmProviderDescriptor) =>
      data.map((modelData) => {
        const existingConfig = llmProviderDescriptor.model_configurations.find(
          (config) => config.name === modelData.name
        );
        return {
          name: modelData.name,
          display_name: modelData.display_name,
          is_visible: existingConfig?.is_visible ?? true,
          max_input_tokens: modelData.max_input_tokens,
          supports_image_input: modelData.supports_image_input,
        };
      }),
    getModelNames: (data: OllamaModelResponse[]) =>
      data.map((model) => model.name),
    successMessage: (count: number) =>
      `Successfully fetched ${count} models from Ollama.`,
  },
  openrouter: {
    endpoint: "/api/admin/llm/openrouter/available-models",
    isDisabled: (values) => !values.api_base || !values.api_key,
    disabledReason:
      "API Base and API Key are required to fetch OpenRouter models",
    buildRequestBody: ({ values, existingLlmProvider }) => ({
      api_base: values.api_base,
      api_key: values.api_key,
      provider_name: existingLlmProvider?.name,
    }),
    processResponse: (data: OpenRouterModelResponse[], llmProviderDescriptor) =>
      data.map((modelData) => {
        const existingConfig = llmProviderDescriptor.model_configurations.find(
          (config) => config.name === modelData.name
        );
        return {
          name: modelData.name,
          display_name: modelData.display_name,
          is_visible: existingConfig?.is_visible ?? true,
          max_input_tokens: modelData.max_input_tokens,
          supports_image_input: modelData.supports_image_input,
        };
      }),
    getModelNames: (data: OpenRouterModelResponse[]) => data.map((m) => m.name),
    successMessage: (count: number) =>
      `Successfully fetched ${count} models from OpenRouter.`,
  },
};

export const fetchModels = async (
  llmProviderDescriptor: WellKnownLLMProviderDescriptor,
  existingLlmProvider: LLMProviderView | undefined,
  values: any,
  setFieldValue: any,
  setIsFetchingModels: (loading: boolean) => void,
  setFetchModelsError: (error: string) => void,
  setPopup?: (popup: PopupSpec) => void
) => {
  const config = dynamicProviderConfigs[llmProviderDescriptor.name];
  if (!config) {
    return;
  }

  if (config.isDisabled(values)) {
    setFetchModelsError(config.disabledReason);
    return;
  }

  setIsFetchingModels(true);
  setFetchModelsError("");

  try {
    let updatedModelConfigs: ModelConfiguration[];
    let availableModelNames: string[];

    if (config.isStatic) {
      // For static providers, use models from the descriptor (which comes from litellm)
      // Preserve visibility settings from existing provider if editing
      const existingVisibleModels = new Set(
        existingLlmProvider?.model_configurations
          .filter((m) => m.is_visible)
          .map((m) => m.name) || []
      );

      updatedModelConfigs = llmProviderDescriptor.model_configurations.map(
        (model) => ({
          ...model,
          // Preserve visibility if model existed before, otherwise default to false
          is_visible: existingVisibleModels.has(model.name)
            ? true
            : model.is_visible,
        })
      );
      availableModelNames = updatedModelConfigs.map((m) => m.name);
    } else {
      // For dynamic providers, fetch from the API
      const response = await fetch(config.endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(
          config.buildRequestBody({ values, existingLlmProvider })
        ),
      });

      if (!response.ok) {
        let errorMessage = "Failed to fetch models";
        try {
          const errorData = await response.json();
          errorMessage = errorData.detail || errorMessage;
        } catch {
          // ignore JSON parsing errors and use the fallback message
        }
        throw new Error(errorMessage);
      }

      const availableModels = await response.json();
      updatedModelConfigs = config.processResponse(
        availableModels,
        llmProviderDescriptor
      );
      availableModelNames = config.getModelNames(availableModels);
    }

    // Store the updated model configurations in form state instead of mutating props
    setFieldValue("fetched_model_configurations", updatedModelConfigs);

    // Update selected model names to only include previously visible models that are available
    const previouslySelectedModels = values.selected_model_names || [];
    const stillAvailableSelectedModels = previouslySelectedModels.filter(
      (modelName: string) => availableModelNames.includes(modelName)
    );
    setFieldValue("selected_model_names", stillAvailableSelectedModels);

    // Set a default model if none is set
    if (
      (!values.default_model_name ||
        !availableModelNames.includes(values.default_model_name)) &&
      availableModelNames.length > 0
    ) {
      setFieldValue("default_model_name", availableModelNames[0]);
    }

    // Clear fast model if it's not in the new list
    if (
      values.fast_default_model_name &&
      !availableModelNames.includes(values.fast_default_model_name)
    ) {
      setFieldValue("fast_default_model_name", null);
    }

    // Force a re-render by updating a timestamp or counter
    setFieldValue("_modelListUpdated", Date.now());

    setPopup?.({
      message: config.successMessage(availableModelNames.length),
      type: "success",
    });
  } catch (error) {
    const errorMessage =
      error instanceof Error ? error.message : "Unknown error";
    setFetchModelsError(errorMessage);
    setPopup?.({
      message: `Failed to fetch models: ${errorMessage}`,
      type: "error",
    });
  } finally {
    setIsFetchingModels(false);
  }
};
