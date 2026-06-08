// Mirrors web languageModels/types.ts (subset the mobile model selector needs).

export interface ModelConfiguration {
  id?: number;
  name: string;
  is_visible: boolean;
  max_input_tokens: number | null;
  supports_image_input: boolean;
  supports_reasoning: boolean;
  display_name?: string;
  // Admin override — wins over display_name everywhere.
  custom_display_name?: string;
  provider_display_name?: string;
  vendor?: string;
  version?: string;
  region?: string;
}

export interface LLMProviderDescriptor {
  id: number;
  name: string | null;
  provider: string;
  provider_display_name: string;
  model_configurations: ModelConfiguration[];
}

export interface DefaultModel {
  provider_id: number;
  model_name: string;
}

export interface LLMProviderResponse {
  providers: LLMProviderDescriptor[];
  default_text: DefaultModel | null;
  default_vision: DefaultModel | null;
}

// A single selectable model, flattened from a provider's visible model_configurations.
export interface LLMOption {
  name: string;
  provider: string;
  providerDisplayName: string;
  modelName: string;
  displayName: string;
  vendor?: string;
  supportsReasoning: boolean;
  supportsImageInput: boolean;
}

export interface SelectedModel {
  name: string;
  provider: string;
  modelName: string;
  displayName: string;
}
