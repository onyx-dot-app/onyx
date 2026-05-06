import type { IconFunctionComponent } from "@opal/types";

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

export enum EmbeddingProviderName {
  // Cloud-based
  OPENAI = "openai",
  COHERE = "cohere",
  VOYAGE = "voyage",
  GOOGLE = "google",
  LITELLM = "litellm",
  AZURE = "azure",

  // Self-hosted
  NOMIC = "nomic",
  MICROSOFT = "microsoft",

  // Custom self-hosted (frontend-only sentinel; backend stores provider_type=null)
  CUSTOM = "custom",
}

export enum RerankerProvider {
  COHERE = "cohere",
  LITELLM = "litellm",
  BEDROCK = "bedrock",
}

export enum SwitchoverType {
  REINDEX = "reindex",
  ACTIVE_ONLY = "active_only",
  INSTANT = "instant",
}

export enum EmbeddingPrecision {
  FLOAT = "float",
  BFLOAT16 = "bfloat16",
}

// ---------------------------------------------------------------------------
// Frontend / Registry Types
// Frontend-only shapes that carry display info (icons, links, descriptions)
// not stored on the backend.
// ---------------------------------------------------------------------------

export interface EmbeddingProvider {
  providerName: EmbeddingProviderName;
  displayName: string;
  icon: IconFunctionComponent;
  docsLink?: string;
  costslink?: string;
  apiLink?: string;
  embeddingModels: EmbeddingModel[];

  /**
   * When true, this provider is no longer recommended for new deployments.
   * Existing usage is allowed, but selecting it as a new embedding model is
   * blocked in the UI.
   */
  deprecated?: boolean;
}

export interface EmbeddingModel {
  modelName: string;
  modelDim?: number | null;
  normalize: boolean;
  queryPrefix?: string | null;
  passagePrefix?: string | null;
  description: string;
}

export interface RerankingModel {
  rerank_provider_type: RerankerProvider | null;
  modelName?: string;
  displayName: string;
  description: string;
  link: string;
  cloud: boolean;
}

export type EmbeddingModelState =
  | "unconnected"
  | "connected"
  | "current"
  | "selected";

// ---------------------------------------------------------------------------
// API Wire Types (Request / Response)
// Exact shapes sent to / received from the backend. Use snake_case to mirror
// the JSON payload; camelCase aliases live only in the frontend registry types
// above.
// ---------------------------------------------------------------------------

/**
 * Shape returned by the backend for a persisted embedding model.
 * No `description` — that's frontend-only marketing copy.
 */
export interface EmbeddingModelResponse {
  id?: number;
  model_name: string;
  model_dim: number;
  normalize: boolean;
  query_prefix: string | null;
  passage_prefix: string | null;
  provider_type: EmbeddingProviderName | null;
  api_key: string | null;
  api_url: string | null;
  index_name: string | null;
  switchover_type?: SwitchoverType;
}

/** Payload sent when switching to a new embedding model. */
export interface EmbeddingModelRequest {
  modelName?: string | null;
  modelDim?: number | null;
  normalize: boolean;
  queryPrefix?: string | null;
  passagePrefix?: string | null;
}

/** Shape returned by `GET /api/admin/embedding/embedding-provider`. */
export interface ConfiguredEmbeddingProvider {
  provider_type: EmbeddingProviderName;
  api_key: string | null;
  api_url: string | null;
  api_version: string | null;
  deployment_name: string | null;
}

export interface RerankingDetails {
  rerank_model_name: string | null;
  rerank_provider_type: RerankerProvider | null;
  rerank_api_key: string | null;
  rerank_api_url: string | null;
}

export interface AdvancedSearchConfiguration {
  index_name: string | null;
  multipass_indexing: boolean;
  enable_contextual_rag: boolean;
  contextual_rag_llm_name: string | null;
  contextual_rag_llm_provider: string | null;
  multilingual_expansion: string[];
  disable_rerank_for_streaming: boolean;
  api_url: string | null;
  num_rerank: number;
  embedding_precision: EmbeddingPrecision;
  reduced_dimension: number | null;
}

export interface SavedSearchSettings
  extends RerankingDetails,
    AdvancedSearchConfiguration {
  model_name: string;
  model_dim: number;
  normalize: boolean;
  query_prefix: string | null;
  passage_prefix: string | null;
  provider_type: EmbeddingProviderName | null;
  switchover_type?: SwitchoverType;
}

export interface LLMContextualCost {
  provider_name: string;
  model_name: string;
  cost: number;
}
