import type { IconFunctionComponent } from "@opal/types";

// Base embedding types

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

// Backend API Response Type

/**
 * The backend-persisted shape for an embedding model. Reflects what the
 * server actually sends/stores — notably **no `description`**, since
 * descriptions are frontend-only marketing copy on the registry types
 * ({@link EmbeddingModel}).
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

// Embedding Providers + Models

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

export interface EmbeddingModelRequest {
  modelName: string;
  modelDim?: number | null;
  normalize: boolean;
  queryPrefix?: string | null;
  passagePrefix?: string | null;
  description?: string | null;
}

// Reranking

export enum RerankerProvider {
  COHERE = "cohere",
  LITELLM = "litellm",
  BEDROCK = "bedrock",
}

// This is a slightly different interface than used in the backend
// but is always used in conjunction with `AdvancedSearchConfiguration`.
export interface RerankingDetails {
  rerank_model_name: string | null;
  rerank_provider_type: RerankerProvider | null;
  rerank_api_key: string | null;
  rerank_api_url: string | null;
}

export interface RerankingModel {
  rerank_provider_type: RerankerProvider | null;
  modelName?: string;
  displayName: string;
  description: string;
  link: string;
  cloud: boolean;
}

// Search / indexing settings

export enum SwitchoverType {
  REINDEX = "reindex",
  ACTIVE_ONLY = "active_only",
  INSTANT = "instant",
}

export enum EmbeddingPrecision {
  FLOAT = "float",
  BFLOAT16 = "bfloat16",
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
  provider_type: EmbeddingProviderName | null;
  switchover_type?: SwitchoverType;
}

export interface LLMContextualCost {
  provider: string;
  model_name: string;
  cost: number;
}

// Embedding model card state

export type EmbeddingModelState =
  | "unconnected"
  | "connected"
  | "current"
  | "selected";

/** Shape returned by `GET /api/admin/embedding/embedding-provider`. */
export interface ConfiguredEmbeddingProvider {
  provider_type: EmbeddingProviderName;
  api_key: string | null;
  api_url: string | null;
  api_version: string | null;
  deployment_name: string | null;
}
