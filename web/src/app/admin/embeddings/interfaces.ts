import {
  AVAILABLE_CLOUD_PROVIDERS,
  AVAILABLE_MODELS,
  CloudEmbeddingModel,
  EmbeddingProvider,
  HostedEmbeddingModel,
} from "@/components/embedding/interfaces";

// This is a slightly differnte interface than used in the backend
// but is always used in conjunction with `AdvancedSearchConfiguration`
export interface RerankingDetails {
  rerank_model_name: string | null;
  rerank_provider_type: RerankerProvider | null;
  rerank_api_key: string | null;
  rerank_api_url: string | null;
}

export enum RerankerProvider {
  COHERE = "cohere",
  LITELLM = "litellm",
  BEDROCK = "bedrock",
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
  background_reindex_enabled: boolean;
}

export interface RerankingModel {
  rerank_provider_type: RerankerProvider | null;
  modelName?: string;
  displayName: string;
  description: string;
  link: string;
  cloud: boolean;
}

export const rerankingModels: RerankingModel[] = [
  {
    rerank_provider_type: RerankerProvider.LITELLM,
    cloud: true,
    displayName: "LiteLLM",
    description: "Host your own reranker or router with LiteLLM proxy",
    link: "https://docs.litellm.ai/docs/simple_proxy",
  },
  {
    rerank_provider_type: null,
    cloud: false,
    modelName: "mixedbread-ai/mxbai-rerank-xsmall-v1",
    displayName: "MixedBread XSmall",
    description: "Fastest, smallest model for basic reranking tasks.",
    link: "https://huggingface.co/mixedbread-ai/mxbai-rerank-xsmall-v1",
  },
  {
    rerank_provider_type: null,
    cloud: false,
    modelName: "mixedbread-ai/mxbai-rerank-base-v1",
    displayName: "MixedBread Base",
    description: "Balanced performance for general reranking needs.",
    link: "https://huggingface.co/mixedbread-ai/mxbai-rerank-base-v1",
  },
  {
    rerank_provider_type: null,
    cloud: false,
    modelName: "mixedbread-ai/mxbai-rerank-large-v1",
    displayName: "MixedBread Large",
    description: "Most powerful model for complex reranking tasks.",
    link: "https://huggingface.co/mixedbread-ai/mxbai-rerank-large-v1",
  },
  {
    cloud: true,
    rerank_provider_type: RerankerProvider.COHERE,
    modelName: "rerank-english-v3.0",
    displayName: "Cohere English",
    description: "High-performance English-focused reranking model.",
    link: "https://docs.cohere.com/v2/reference/rerank",
  },
  {
    cloud: true,
    rerank_provider_type: RerankerProvider.COHERE,
    modelName: "rerank-multilingual-v3.0",
    displayName: "Cohere Multilingual",
    description: "Powerful multilingual reranking model.",
    link: "https://docs.cohere.com/v2/reference/rerank",
  },
  {
    cloud: true,
    rerank_provider_type: RerankerProvider.BEDROCK,
    modelName: "cohere.rerank-v3-5:0",
    displayName: "Cohere Rerank 3.5",
    description:
      "Powerful multilingual reranking model invoked through AWS Bedrock.",
    link: "https://aws.amazon.com/blogs/machine-learning/cohere-rerank-3-5-is-now-available-in-amazon-bedrock-through-rerank-api",
  },
];

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
