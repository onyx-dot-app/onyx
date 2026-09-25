import type { OnboardingActions } from "@/interfaces/onboarding";
import type { LLMProviderConfiguredSource } from "@/lib/analytics/utils";
import type { FunctionComponent } from "react";
import type { IconFunctionComponent, IconProps } from "@opal/types";

/**
 * Per-session reasoning-effort override. Mirrors the backend ReasoningEffort
 * enum minus "auto", since no override (null) already means auto.
 */
export type ReasoningEffortOverride =
  | "off"
  | "low"
  | "medium"
  | "high"
  | "xhigh";

export interface ModelConfiguration {
  id?: number;
  name: string;
  is_visible: boolean;
  max_input_tokens: number | null;
  supports_image_input: boolean;
  supports_reasoning: boolean;
  /**
   * Effort levels this model tells apart, ascending, as resolved by the
   * backend that builds the request. Absent from an older backend, in which
   * case the picker falls back to the levels every reasoning model supports.
   */
  supported_reasoning_efforts?: ReasoningEffortOverride[];
  /** What the admin permits or defaults, distinct from
   *  supported_reasoning_efforts (what the model can do). Null means unset. */
  reasoning_effort_max?: ReasoningEffortOverride | null;
  reasoning_effort_default?: ReasoningEffortOverride | null;
  temperature_default?: number | null;
  /** Display-only metadata surfaced in the model picker (Nebius TokenFactory). */
  quantization?: string | null;
  country_code?: string | null;
  requests_per_minute?: number | null;
  supported_features?: string[];
  /** True when this is the provider's recommended default model. */
  is_recommended_default?: boolean;
  display_name?: string;
  /** Admin-set override that takes precedence over display_name everywhere in the UI. */
  custom_display_name?: string;
  provider_display_name?: string;
  vendor?: string;
  version?: string;
  region?: string;
  /**
   * Frontend-derived. Always populated by the SWR hooks before data reaches
   * any consumer. Resolution order: custom_display_name → display_name → name.
   * Use this field everywhere a model name is rendered — never read
   * custom_display_name / display_name / name directly for display purposes.
   */
  effectiveDisplayName: string;
}

export enum LLMProviderName {
  OPENAI = "openai",
  ANTHROPIC = "anthropic",
  OLLAMA_CHAT = "ollama_chat",
  LM_STUDIO = "lm_studio",
  AZURE = "azure",
  OPENROUTER = "openrouter",
  VERTEX_AI = "vertex_ai",
  BEDROCK = "bedrock",
  LITELLM = "litellm",
  LITELLM_PROXY = "litellm_proxy",
  BIFROST = "bifrost",
  OPENAI_COMPATIBLE = "openai_compatible",
  NEBIUS_TOKENFACTORY = "nebius_tokenfactory",
  PORTKEY = "portkey",
  VERCEL_AI_GATEWAY = "vercel_ai_gateway",
  CUSTOM = "custom",
}

export type PortkeyApiMode = "chat_completions" | "responses" | "messages";

export type BifrostApiMode = "chat_completions" | "responses";

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
  name: string | null;
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
  name: string | null;
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

export interface LMStudioModelResponse {
  name: string;
  display_name: string;
  max_input_tokens: number | null;
  supports_image_input: boolean;
  supports_reasoning: boolean;
}

export interface DefaultModel {
  provider_id: number;
  model_name: string;
}

export interface LLMProviderResponse<T> {
  providers: T[];
  default_text: DefaultModel | null;
  default_vision: DefaultModel | null;
  default_chat_naming: DefaultModel | null;
  default_craft: DefaultModel | null;
}

export type LLMModalVariant = "onboarding" | "llm-configuration";

export interface LLMProviderFormProps {
  variant?: LLMModalVariant;
  existingLlmProvider?: LLMProviderView;
  shouldMarkAsDefault?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Called after successful provider creation/update. */
  onSuccess?: () => void | Promise<void>;
  /** Overrides the analytics source derived from the variant. */
  analyticsSource?: LLMProviderConfiguredSource;

  // Onboarding-specific (only when variant === "onboarding")
  onboardingActions?: OnboardingActions;
}

export interface BedrockFetchParams {
  aws_region_name: string;
  aws_access_key_id?: string;
  aws_secret_access_key?: string;
  aws_bearer_token_bedrock?: string;
  provider_id?: number;
}

export interface OllamaFetchParams {
  api_base?: string;
  provider_id?: number;
  signal?: AbortSignal;
}

export interface OpenRouterFetchParams {
  api_base?: string;
  api_key?: string;
  provider_id?: number;
}

export interface LiteLLMProxyFetchParams {
  api_base?: string;
  api_key?: string;
  provider_id?: number;
  signal?: AbortSignal;
}

export interface LiteLLMProxyModelResponse {
  provider_name: string;
  model_name: string;
  litellm_params_model: string;
  max_input_tokens: number | null;
  supports_image_input: boolean;
  supports_reasoning: boolean;
}

export interface BifrostFetchParams {
  api_base?: string;
  api_key?: string;
  provider_id?: number;
  signal?: AbortSignal;
}

export interface BifrostModelResponse {
  name: string;
  display_name: string;
  max_input_tokens: number | null;
  supports_image_input: boolean;
  supports_reasoning: boolean;
}

export interface OpenAICompatibleFetchParams {
  api_base?: string;
  api_key?: string;
  provider_id?: number;
  signal?: AbortSignal;
}

export interface OpenAICompatibleModelResponse {
  name: string;
  display_name: string;
  max_input_tokens: number | null;
  supports_image_input: boolean;
  supports_reasoning: boolean;
}

export interface NebiusTokenfactoryFetchParams {
  api_base?: string;
  api_key?: string;
  provider_id?: number;
  signal?: AbortSignal;
}

export interface NebiusTokenfactoryModelResponse {
  name: string;
  display_name: string;
  max_input_tokens: number | null;
  supports_image_input: boolean;
  supports_reasoning: boolean;
  quantization: string | null;
  country_code: string | null;
  requests_per_minute: number | null;
  supported_features: string[];
}

export interface PortkeyFetchParams {
  api_base?: string;
  api_key?: string;
  provider_id?: number;
  signal?: AbortSignal;
}

export interface PortkeyModelResponse {
  name: string;
  display_name: string;
  max_input_tokens: number | null;
  supports_image_input: boolean;
  supports_reasoning: boolean;
}

export interface VercelAIGatewayFetchParams {
  api_base?: string;
  api_key?: string;
  provider_id?: number;
  signal?: AbortSignal;
}

export interface VercelAIGatewayModelResponse {
  name: string;
  display_name: string;
  max_input_tokens: number | null;
  supports_image_input: boolean;
  supports_reasoning: boolean;
}

export interface VertexAIFetchParams {
  model_configurations?: ModelConfiguration[];
}

export interface LMStudioFetchParams {
  api_base?: string;
  api_key?: string;
  api_key_changed?: boolean;
  provider_id?: number;
  signal?: AbortSignal;
}

export type FetchModelsParams =
  | BedrockFetchParams
  | OllamaFetchParams
  | OpenRouterFetchParams
  | LiteLLMProxyFetchParams
  | BifrostFetchParams
  | OpenAICompatibleFetchParams
  | VertexAIFetchParams
  | LMStudioFetchParams;

// ---------------------------------------------------------------------------
// Option, hook and registry shapes
// ---------------------------------------------------------------------------

export type ModelOptionProvider = Pick<
  LLMProviderDescriptor,
  "id" | "name" | "provider" | "model_configurations"
>;

export interface LLMOption {
  name: string;
  provider: string;
  providerDisplayName: string;
  modelName: string;
  modelConfigurationId?: number | null;
  displayName: string;
  description?: string;
  vendor: string | null;
  maxInputTokens?: number | null;
  region?: string | null;
  version?: string | null;
  supportsReasoning?: boolean;
  /** See ModelConfiguration.supported_reasoning_efforts. */
  supportedReasoningEfforts?: ReasoningEffortOverride[];
  /** See ModelConfiguration.reasoning_effort_max. */
  reasoningEffortMax?: ReasoningEffortOverride | null;
  reasoningEffortDefault?: ReasoningEffortOverride | null;
  temperatureDefault?: number | null;
  supportsImageInput?: boolean;
}

export interface LLMOptionGroup {
  key: string;
  displayName: string;
  options: LLMOption[];
  Icon: FunctionComponent<IconProps>;
}

export interface CustomProviderOption {
  value: string;
  label: string;
}

export interface DefaultLlmReference {
  /**
   * The provider row this default belongs to. `llm_provider.name` carries no
   * unique constraint and is nullable, so it can neither identify a provider
   * nor be relied on to exist. Always key off this.
   */
  providerId: number;
  modelName: string;
}

export interface LlmDefaults {
  /** Raw provider list, passed through from `useLanguageModels`. */
  llmProviders: LLMProviderDescriptor[] | undefined;
  /** True iff any provider exposes at least one visible model. */
  hasAnyLlm: boolean;
  /** True iff any provider exposes a visible model with `supports_image_input`. */
  hasAnyVisionLlm: boolean;
  /**
   * The admin-configured default text model as `{ providerId, modelName }`.
   * The backend stores `default_text` as `{ provider_id, model_name }`; this
   * hook only confirms the provider is still in the list.
   */
  defaultLlm: DefaultLlmReference | null;
  /**
   * The admin-configured default *vision* model, in the same shape as
   * `defaultLlm`. Used by indexing-time captioning and any other vision-only
   * feature.
   */
  defaultVision: DefaultLlmReference | null;
  isLoading: boolean;
}

/**
 * Admin-set negotiated per-model rate, overriding the built-in price book.
 * Rates are USD per MILLION tokens. Keyed on (provider, model); provider is ""
 * for a provider-agnostic override.
 */
export interface CostOverride {
  model: string;
  provider: string;
  input_cost_per_mtok: number;
  output_cost_per_mtok: number;
  cache_read_cost_per_mtok: number | null; // null = bill cache at the input rate
  updated_at: string | null;
}

/** PUT body — an idempotent upsert keyed on (provider, model). */
export interface CostOverrideUpsert {
  model: string;
  provider?: string; // "" / omitted = provider-agnostic
  input_cost_per_mtok: number;
  output_cost_per_mtok: number;
  cache_read_cost_per_mtok: number | null;
}

export interface ProviderEntry {
  icon: IconFunctionComponent;
  productName: string;
  companyName: string;
  Modal: React.ComponentType<LLMProviderFormProps>;
}

export interface ModelIconProps extends IconProps {
  provider: string;
  modelName?: string;
}
