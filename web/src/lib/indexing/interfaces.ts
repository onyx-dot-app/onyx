import type { IconFunctionComponent } from "@opal/types";

// ─── Embedding providers ─────────────────────────────────────────────────────

export enum EmbeddingProvider {
  OPENAI = "openai",
  COHERE = "cohere",
  VOYAGE = "voyage",
  GOOGLE = "google",
  LITELLM = "litellm",
  AZURE = "azure",
}

export interface CloudEmbeddingProvider {
  provider_type: EmbeddingProvider;
  api_key?: string;
  api_url?: string;
  custom_config?: Record<string, string>;
  docsLink?: string;

  // Frontend-specific properties
  website: string;
  icon: IconFunctionComponent;
  description: string;
  apiLink: string;
  costslink?: string;

  /**
   * When true, this provider is no longer recommended for new deployments.
   * Existing usage is allowed, but selecting it as a new embedding model is
   * blocked in the UI.
   */
  deprecated?: boolean;

  // Relationships
  embedding_models: CloudEmbeddingModel[];
  default_model?: CloudEmbeddingModel;
}

export interface CloudEmbeddingProviderFull extends CloudEmbeddingProvider {
  configured?: boolean;
}

// ─── Embedding models ────────────────────────────────────────────────────────

/**
 * The backend-persisted shape for an embedding model. Reflects what the
 * server actually sends/stores — notably **no `description`**, since
 * descriptions are frontend-only marketing copy on the registry types
 * ({@link CloudEmbeddingModel}, {@link SelfHostedEmbeddingModel}).
 */
export interface EmbeddingModelDescriptor {
  id?: number;
  model_name: string;
  model_dim: number;
  normalize: boolean;
  query_prefix: string;
  passage_prefix: string;
  provider_type: EmbeddingProvider | null;
  api_key: string | null;
  api_url: string | null;
  api_version?: string | null;
  deployment_name?: string | null;
  index_name: string | null;
  switchover_type?: SwitchoverType;
}

export interface CloudEmbeddingModel extends EmbeddingModelDescriptor {
  description: string;
  pricePerMillion: number;
}

export interface SelfHostedEmbeddingModel extends EmbeddingModelDescriptor {
  description: string;
  link?: string;
  isDefault?: boolean;
}

export interface SelfHostedEmbeddingProvider {
  provider_name: string;
  icon: IconFunctionComponent;
  docsLink?: string;
  embedding_models: SelfHostedEmbeddingModel[];
}

// ─── Reranking ───────────────────────────────────────────────────────────────

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

// ─── Search / indexing settings ──────────────────────────────────────────────

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
  provider_type: EmbeddingProvider | null;
  switchover_type?: SwitchoverType;
}

export interface LLMContextualCost {
  provider: string;
  model_name: string;
  cost: number;
}

// ─── Embedding model card state ─────────────────────────────────────────────

export type EmbeddingModelState =
  | "unconnected"
  | "connected"
  | "current"
  | "selected";

/** Shape returned by `GET /api/admin/embedding/embedding-provider`. */
export interface ConfiguredEmbeddingProvider {
  provider_type: EmbeddingProvider;
  api_key: string | null;
  api_url: string | null;
  api_version: string | null;
  deployment_name: string | null;
}
