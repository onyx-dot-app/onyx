// Mirrors web languageModels/types.ts (only the fields the mobile model selector
// needs). The backend returns `LLMProviderDescriptor[]` from GET /llm/provider.

export interface ModelConfiguration {
  id?: number;
  /** The model_version sent to the API (e.g. "gpt-4o"). */
  name: string;
  is_visible: boolean;
  max_input_tokens: number | null;
  supports_image_input: boolean;
  supports_reasoning: boolean;
  display_name?: string;
  /** Admin override — wins over display_name everywhere. */
  custom_display_name?: string;
  provider_display_name?: string;
  /** For aggregator providers (e.g. Bedrock) to group/sort by underlying vendor. */
  vendor?: string;
  version?: string;
  region?: string;
}

export interface LLMProviderDescriptor {
  id: number;
  /** Provider *instance* name (e.g. "OpenAI Prod"). Maps to llm_override.model_provider. */
  name: string | null;
  /** Provider *kind* (e.g. "openai", "bedrock"). */
  provider: string;
  provider_display_name: string;
  model_configurations: ModelConfiguration[];
}

/** Workspace/persona default model pointer (provider id + model_version). */
export interface DefaultModel {
  provider_id: number;
  model_name: string;
}

/**
 * Response of GET /llm/provider (and /llm/persona/{id}/providers). Both endpoints
 * wrap the descriptors — the web `useLLMProviders` hook reads `.providers`.
 */
export interface LLMProviderResponse {
  providers: LLMProviderDescriptor[];
  default_text: DefaultModel | null;
  default_vision: DefaultModel | null;
}

/** A single selectable model, flattened from a provider's visible model_configurations. */
export interface LLMOption {
  /** Provider instance name → llm_override.model_provider. "" if the provider has no name. */
  name: string;
  /** Provider kind (used for grouping + icon resolution). */
  provider: string;
  providerDisplayName: string;
  /** model_configuration.name → llm_override.model_version. */
  modelName: string;
  /** Resolved display name (custom_display_name || display_name || name). */
  displayName: string;
  vendor?: string;
  supportsReasoning: boolean;
  supportsImageInput: boolean;
}

/** The per-session selected model persisted in the chat store + sent as llm_override. */
export interface SelectedModel {
  /** Provider instance name → llm_override.model_provider. */
  name: string;
  provider: string;
  /** → llm_override.model_version. */
  modelName: string;
  displayName: string;
}
