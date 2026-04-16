import {
  AVAILABLE_CLOUD_PROVIDERS,
  AVAILABLE_MODELS,
  CloudEmbeddingModel,
  EmbeddingProvider,
  HostedEmbeddingModel,
} from "@/components/embedding/interfaces";

export enum SwitchoverType {
  REINDEX = "reindex",
  ACTIVE_ONLY = "active_only",
  INSTANT = "instant",
}

export enum EmbeddingPrecision {
  FLOAT = "float",
  BFLOAT16 = "bfloat16",
}

export interface LLMContextualCost {
  provider: string;
  model_name: string;
  cost: number;
}

export interface AdvancedSearchConfiguration {
  index_name: string | null;
  multipass_indexing: boolean;
  enable_contextual_rag: boolean;
  contextual_rag_llm_name: string | null;
  contextual_rag_llm_provider: string | null;
  multilingual_expansion: string[];
  api_url: string | null;
  embedding_precision: EmbeddingPrecision;
  reduced_dimension: number | null;
}

export interface SavedSearchSettings extends AdvancedSearchConfiguration {
  provider_type: EmbeddingProvider | null;
  switchover_type?: SwitchoverType;
}

export const getCurrentModelCopy = (
  currentModelName: string
): CloudEmbeddingModel | HostedEmbeddingModel | null => {
  const AVAILABLE_CLOUD_PROVIDERS_FLATTENED = AVAILABLE_CLOUD_PROVIDERS.flatMap(
    (provider) =>
      provider.embedding_models.map((model) => ({
        ...model,
        provider_type: provider.provider_type,
        model_name: model.model_name,
      }))
  );

  return (
    AVAILABLE_MODELS.find((model) => model.model_name === currentModelName) ||
    AVAILABLE_CLOUD_PROVIDERS_FLATTENED.find(
      (model) => model.model_name === currentModelName
    ) ||
    null
  );
};
