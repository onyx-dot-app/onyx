import { EmbeddingProvider } from "@/components/embedding/interfaces";
import { NonNullChain } from "typescript";

export interface RerankingDetails {
  rerank_model_name: string | null;
  rerank_provider_type: RerankerProvider | null;
  rerank_api_key: string | null;
  num_rerank: number;
}

export enum RerankerProvider {
  COHERE = "cohere",
}
export interface AdvancedSearchConfiguration {
  model_name: string;
  model_dim: number;
  normalize: boolean;
  query_prefix: string;
  passage_prefix: string;
  index_name: string | null;
  multipass_indexing: boolean;
  multilingual_expansion: string[];
  disable_rerank_for_streaming: boolean;
  api_url: string | null;
}

export interface SavedSearchSettings extends RerankingDetails {
  model_name: string;
  model_dim: number;
  normalize: boolean;
  query_prefix: string;
  passage_prefix: string;
  index_name: string | null;
  multipass_indexing: boolean;
  multilingual_expansion: string[];
  disable_rerank_for_streaming: boolean;
  api_url: string | null;
  provider_type: EmbeddingProvider | null;
}

export interface RerankingModel {
  rerank_provider_type: RerankerProvider | null;
  modelName: string;
  displayName: string;
  description: string;
  link: string;
  cloud: boolean;
}

export const rerankingModels: RerankingModel[] = [
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
    link: "https://docs.cohere.com/docs/rerank",
  },
  {
    cloud: true,
    rerank_provider_type: RerankerProvider.COHERE,
    modelName: "rerank-multilingual-v3.0",
    displayName: "Cohere Multilingual",
    description: "Powerful multilingual reranking model.",
    link: "https://docs.cohere.com/docs/rerank",
  },
];
