import { PopupSpec } from "@/components/admin/connectors/Popup";

export enum LLMProviderName {
  OPENAI = "openai",
  ANTHROPIC = "anthropic",
  OLLAMA_CHAT = "ollama_chat",
  AZURE = "azure",
  OPENROUTER = "openrouter",
  VERTEX_AI = "vertex_ai",
  BEDROCK = "bedrock",
}

export interface CustomConfigOption {
  label: string;
  value: string;
  description?: string | null;
}

export interface CustomConfigKey {
  name: string;
  display_name: string;
  description: string | null;
  is_required: boolean;
  is_secret: boolean;
  key_type: CustomConfigKeyType;
  default_value?: string;
  options?: CustomConfigOption[] | null;
}

export type CustomConfigKeyType = "text_input" | "file_input" | "select";

export interface ModelConfiguration {
  name: string;
  is_visible: boolean;
  max_input_tokens: number | null;
  supports_image_input: boolean | null;
  supports_reasoning?: boolean;
  display_name?: string;
  provider_display_name?: string;
  vendor?: string;
  version?: string;
  region?: string;
}

export interface WellKnownLLMProviderDescriptor {
  name: string;
  display_name: string;
  title: string;

  deployment_name_required: boolean;
  api_key_required: boolean;
  api_base_required: boolean;
  api_version_required: boolean;

  single_model_supported: boolean;
  custom_config_keys: CustomConfigKey[] | null;
  model_configurations: ModelConfiguration[];
  default_model: string | null;
  default_fast_model: string | null;
  default_api_base: string | null;
  is_public: boolean;
  groups: number[];
}

export interface LLMModelDescriptor {
  modelName: string;
  provider: string;
  maxTokens: number;
}

export interface LLMProvider {
  name: string;
  provider: string;
  api_key: string | null;
  api_base: string | null;
  api_version: string | null;
  custom_config: { [key: string]: string } | null;
  default_model_name: string;
  fast_default_model_name: string | null;
  is_public: boolean;
  groups: number[];
  personas: number[];
  deployment_name: string | null;
  default_vision_model: string | null;
  is_default_vision_provider: boolean | null;
  model_configurations: ModelConfiguration[];
}

export interface LLMProviderView extends LLMProvider {
  id: number;
  is_default_provider: boolean | null;
}

export interface VisionProvider extends LLMProviderView {
  vision_models: string[];
}

export interface LLMProviderDescriptor {
  name: string;
  provider: string;
  provider_display_name?: string;
  default_model_name: string;
  fast_default_model_name: string | null;
  is_default_provider: boolean | null;
  is_default_vision_provider?: boolean | null;
  default_vision_model?: string | null;
  is_public?: boolean;
  groups?: number[];
  personas?: number[];
  model_configurations: ModelConfiguration[];
}

export interface OllamaModelResponse {
  name: string;
  max_input_tokens: number;
  supports_image_input: boolean;
}

export interface DynamicProviderConfig<
  TApiResponse = any,
  TProcessedResponse = ModelConfiguration,
> {
  endpoint: string;
  isDisabled: (values: any) => boolean;
  disabledReason: string;
  buildRequestBody: (args: {
    values: any;
    existingLlmProvider?: LLMProviderView;
  }) => Record<string, any>;
  processResponse: (
    data: TApiResponse,
    llmProviderDescriptor: WellKnownLLMProviderDescriptor
  ) => TProcessedResponse[];
  getModelNames: (data: TApiResponse) => string[];
  successMessage: (count: number) => string;
  // If true, uses models from the descriptor instead of making an API call
  isStatic?: boolean;
}
