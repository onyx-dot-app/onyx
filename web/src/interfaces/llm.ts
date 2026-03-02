export enum LLMProviderName {
  OPENAI = "openai",
  ANTHROPIC = "anthropic",
  OLLAMA_CHAT = "ollama_chat",
  AZURE = "azure",
  OPENROUTER = "openrouter",
  VERTEX_AI = "vertex_ai",
  BEDROCK = "bedrock",
  CUSTOM = "custom",
}

export interface ModelConfiguration {
  name: string;
  is_visible: boolean;
  max_input_tokens: number | null;
  supports_image_input: boolean;
  supports_reasoning: boolean;
  display_name?: string;
  provider_display_name?: string;
  vendor?: string;
  version?: string;
  region?: string;
}

export interface SimpleKnownModel {
  name: string;
  display_name: string | null;
}

export interface WellKnownLLMProviderDescriptor {
  name: string;
  known_models: ModelConfiguration[];
  recommended_default_model: SimpleKnownModel | null;
}

export interface LLMModelDescriptor {
  modelName: string;
  provider: string;
  maxTokens: number;
}

export interface LLMProviderView {
  id: number;
  name: string;
  provider: string;
  api_key: string | null;
  api_base: string | null;
  api_version: string | null;
  custom_config: { [key: string]: string } | null;
  is_public: boolean;
  is_auto_mode: boolean;
  groups: number[];
  personas: number[];
  deployment_name: string | null;
  model_configurations: ModelConfiguration[];
}

export interface VisionProvider extends LLMProviderView {
  vision_models: string[];
}

export interface LLMProviderDescriptor {
  id: number;
  name: string;
  provider: string;
  provider_display_name: string;
  model_configurations: ModelConfiguration[];
}

export interface OllamaModelResponse {
  name: string;
  display_name: string;
  max_input_tokens: number | null;
  supports_image_input: boolean;
}

export interface OpenRouterModelResponse {
  name: string;
  display_name: string;
  max_input_tokens: number | null;
  supports_image_input: boolean;
}

export interface BedrockModelResponse {
  name: string;
  display_name: string;
  max_input_tokens: number;
  supports_image_input: boolean;
}

export interface DefaultModel {
  provider_id: number;
  model_name: string;
}

export interface LLMProviderResponse<T> {
  providers: T[];
  default_text: DefaultModel | null;
  default_vision: DefaultModel | null;
}

export interface LLMProviderFormProps {
  existingLlmProvider?: LLMProviderView;
  shouldMarkAsDefault?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

// Param types for model fetching functions - use snake_case to match API structure
export interface BedrockFetchParams {
  aws_region_name: string;
  aws_access_key_id?: string;
  aws_secret_access_key?: string;
  aws_bearer_token_bedrock?: string;
  provider_name?: string;
}

export interface OllamaFetchParams {
  api_base?: string;
  provider_name?: string;
}

export interface OpenRouterFetchParams {
  api_base?: string;
  api_key?: string;
  provider_name?: string;
}

export interface VertexAIFetchParams {
  model_configurations?: ModelConfiguration[];
}

export type FetchModelsParams =
  | BedrockFetchParams
  | OllamaFetchParams
  | OpenRouterFetchParams
  | VertexAIFetchParams;
