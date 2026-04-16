import { OpenSourceIcon } from "@/components/icons/icons";
import { SvgCpu } from "@opal/icons";
import {
  SvgAzure,
  SvgCohere,
  SvgGoogle,
  SvgLitellm,
  SvgMicrosoft,
  SvgNomic,
  SvgOpenai,
  SvgVoyage,
} from "@opal/logos";
import type { IconFunctionComponent } from "@opal/types";
import {
  CloudEmbeddingModel,
  CloudEmbeddingProvider,
  EmbeddingProvider,
  SelfHostedEmbeddingModel,
  RerankerProvider,
  RerankingModel,
} from "@/lib/indexing/interfaces";
import { DOCS_ADMINS_PATH } from "@/lib/constants";

// ═══════════════════════════════════════════════════════════════════════════
// Embedding
// ═══════════════════════════════════════════════════════════════════════════

// ─── Backend URLs ────────────────────────────────────────────────────────────

export const EMBEDDING_PROVIDERS_ADMIN_URL =
  "/api/admin/embedding/embedding-provider";
export const EMBEDDING_MODELS_ADMIN_URL = "/api/admin/embedding";

// ─── Hosted (self-hosted) embedding models ───────────────────────────────────

export const SELF_HOSTED_MODELS: SelfHostedEmbeddingModel[] = [
  {
    model_name: "nomic-ai/nomic-embed-text-v1",
    model_dim: 768,
    normalize: true,
    description:
      "Nomic’s embedding model specialized for retrieval, similarity, clustering and classification.",
    isDefault: true,
    link: "https://huggingface.co/nomic-ai/nomic-embed-text-v1",
    query_prefix: "search_query: ",
    passage_prefix: "search_document: ",
    index_name: "",
    provider_type: null,
    api_key: null,
    api_url: null,
  },
  {
    model_name: "intfloat/e5-base-v2",
    model_dim: 768,
    normalize: true,
    description:
      "A smaller and faster model than the default. It is around 2x faster than the default model at the cost of lower search quality.",
    link: "https://huggingface.co/intfloat/e5-base-v2",
    query_prefix: "query: ",
    passage_prefix: "passage: ",
    index_name: "",
    provider_type: null,
    api_url: null,
    api_key: null,
  },
  {
    model_name: "intfloat/e5-small-v2",
    model_dim: 384,
    normalize: true,
    description:
      "The smallest and fastest version of the E5 line of models. If you're running Onyx on a resource constrained system, then this may be a good choice.",
    link: "https://huggingface.co/intfloat/e5-small-v2",
    query_prefix: "query: ",
    passage_prefix: "passage: ",
    index_name: "",
    provider_type: null,
    api_key: null,
    api_url: null,
  },
  {
    model_name: "intfloat/multilingual-e5-base",
    model_dim: 768,
    normalize: true,
    description:
      "For corpora in other languages besides English, this is the one to choose.",
    link: "https://huggingface.co/intfloat/multilingual-e5-base",
    query_prefix: "query: ",
    passage_prefix: "passage: ",
    index_name: "",
    provider_type: null,
    api_key: null,
    api_url: null,
  },
  {
    model_name: "intfloat/multilingual-e5-small",
    model_dim: 384,
    normalize: true,
    description:
      "For corpora in other languages besides English, as well as being on a resource constrained system, this is the one to choose.",
    link: "https://huggingface.co/intfloat/multilingual-e5-base",
    query_prefix: "query: ",
    passage_prefix: "passage: ",
    index_name: "",
    provider_type: null,
    api_key: null,
    api_url: null,
  },
];

// ─── Cloud embedding providers ───────────────────────────────────────────────

/**
 * Registry of cloud embedding providers, keyed by {@link EmbeddingProvider}.
 *
 * This is the single source of truth for cloud embedding providers. Add new
 * entries here when introducing a new provider — the `Record` typing forces
 * exhaustiveness, so a missing entry is a compile-time error.
 */
export const CLOUD_EMBEDDING_PROVIDERS: Record<
  EmbeddingProvider,
  CloudEmbeddingProvider
> = {
  [EmbeddingProvider.COHERE]: {
    provider_type: EmbeddingProvider.COHERE,
    website: "https://cohere.ai",
    icon: SvgCohere,
    docsLink: `${DOCS_ADMINS_PATH}/advanced_configs/search_configs`,
    description:
      "AI company specializing in NLP models for various text-based tasks",
    apiLink: "https://dashboard.cohere.ai/api-keys",
    costslink: "https://cohere.com/pricing",
    embedding_models: [
      {
        provider_type: EmbeddingProvider.COHERE,
        model_name: "embed-english-v3.0",
        description:
          "Cohere's English embedding model. Good performance for English-language tasks.",
        pricePerMillion: 0.1,
        model_dim: 1024,
        normalize: false,
        query_prefix: "",
        passage_prefix: "",
        index_name: "",
        api_key: null,
        api_url: null,
      },
      {
        model_name: "embed-english-light-v3.0",
        provider_type: EmbeddingProvider.COHERE,
        description:
          "Cohere's lightweight English embedding model. Faster and more efficient for simpler tasks.",
        pricePerMillion: 0.1,
        model_dim: 384,
        normalize: false,
        query_prefix: "",
        passage_prefix: "",
        index_name: "",
        api_key: null,
        api_url: null,
      },
    ],
  },
  [EmbeddingProvider.OPENAI]: {
    provider_type: EmbeddingProvider.OPENAI,
    website: "https://openai.com",
    icon: SvgOpenai,
    description: "AI industry leader known for ChatGPT and DALL-E",
    apiLink: "https://platform.openai.com/api-keys",
    docsLink: `${DOCS_ADMINS_PATH}/advanced_configs/search_configs`,
    costslink: "https://openai.com/pricing",
    embedding_models: [
      {
        provider_type: EmbeddingProvider.OPENAI,
        model_name: "text-embedding-3-large",
        description:
          "OpenAI's large embedding model. Best performance, but more expensive.",
        pricePerMillion: 0.13,
        model_dim: 3072,
        normalize: false,
        query_prefix: "",
        passage_prefix: "",
        index_name: "",
        api_key: null,
        api_url: null,
      },
      {
        provider_type: EmbeddingProvider.OPENAI,
        model_name: "text-embedding-3-small",
        model_dim: 1536,
        normalize: false,
        query_prefix: "",
        passage_prefix: "",
        description:
          "OpenAI's newer, more efficient embedding model. Good balance of performance and cost.",
        pricePerMillion: 0.02,
        index_name: "",
        api_key: null,
        api_url: null,
      },
    ],
  },
  [EmbeddingProvider.GOOGLE]: {
    provider_type: EmbeddingProvider.GOOGLE,
    website: "https://ai.google",
    icon: SvgGoogle,
    docsLink: `${DOCS_ADMINS_PATH}/advanced_configs/search_configs`,
    description:
      "Offers a wide range of AI services including language and vision models",
    apiLink: "https://console.cloud.google.com/apis/credentials",
    costslink: "https://cloud.google.com/vertex-ai/pricing",
    embedding_models: [
      {
        provider_type: EmbeddingProvider.GOOGLE,
        model_name: "gemini-embedding-001",
        description: "Google's Gemini embedding model. Powerful and efficient.",
        pricePerMillion: 0.025,
        model_dim: 3072,
        normalize: false,
        query_prefix: "",
        passage_prefix: "",
        index_name: "",
        api_key: null,
        api_url: null,
      },
      {
        provider_type: EmbeddingProvider.GOOGLE,
        model_name: "text-embedding-005",
        description: "Smaller, lighter-weight embedding model from Google.",
        pricePerMillion: 0.025,
        model_dim: 768,
        normalize: false,
        query_prefix: "",
        passage_prefix: "",
        index_name: "",
        api_key: null,
        api_url: null,
      },
    ],
  },
  [EmbeddingProvider.VOYAGE]: {
    provider_type: EmbeddingProvider.VOYAGE,
    website: "https://www.voyageai.com",
    icon: SvgVoyage,
    description: "Advanced NLP research startup born from Stanford AI Labs",
    docsLink: `${DOCS_ADMINS_PATH}/advanced_configs/search_configs`,
    apiLink: "https://www.voyageai.com/dashboard",
    costslink: "https://www.voyageai.com/pricing",
    embedding_models: [
      {
        provider_type: EmbeddingProvider.VOYAGE,
        model_name: "voyage-large-2-instruct",
        description:
          "Voyage's large embedding model. High performance with instruction fine-tuning.",
        pricePerMillion: 0.12,
        model_dim: 1024,
        normalize: false,
        query_prefix: "",
        passage_prefix: "",
        index_name: "",
        api_key: null,
        api_url: null,
      },
      {
        provider_type: EmbeddingProvider.VOYAGE,
        model_name: "voyage-light-2-instruct",
        description:
          "Voyage's lightweight embedding model. Good balance of performance and efficiency.",
        pricePerMillion: 0.12,
        model_dim: 1024,
        normalize: false,
        query_prefix: "",
        passage_prefix: "",
        index_name: "",
        api_key: null,
        api_url: null,
      },
    ],
  },
  [EmbeddingProvider.LITELLM]: {
    provider_type: EmbeddingProvider.LITELLM,
    website: "https://github.com/BerriAI/litellm",
    icon: SvgLitellm,
    description: "Open-source library to call LLM APIs using OpenAI format",
    apiLink: "https://docs.litellm.ai/docs/proxy/quick_start",
    embedding_models: [], // No default embedding models
  },
  [EmbeddingProvider.AZURE]: {
    provider_type: EmbeddingProvider.AZURE,
    website:
      "https://azure.microsoft.com/en-us/products/cognitive-services/openai/",
    icon: SvgAzure,
    description:
      "Azure OpenAI is a cloud-based AI service that provides access to OpenAI models.",
    apiLink:
      "https://docs.microsoft.com/en-us/azure/ai-services/openai/how-to/create-resource",
    costslink:
      "https://azure.microsoft.com/en-us/pricing/details/cognitive-services/openai/",
    embedding_models: [], // No default embedding models
  },
};

// ─── Embedding helpers ───────────────────────────────────────────────────────

export function getFormattedProviderName(providerType: string | null) {
  if (!providerType) return "Self-hosted";

  switch (providerType) {
    case "openai":
      return "OpenAI";
    case "cohere":
      return "Cohere";
    case "voyage":
      return "Voyage AI";
    case "google":
      return "Google";
    case "litellm":
      return "LiteLLM";
    case "azure":
      return "Azure";
    default:
      return providerType.charAt(0).toUpperCase() + providerType.slice(1);
  }
}

/**
 * Find the {@link CloudEmbeddingProvider} entry matching `providerType`, or
 * `null` if none matches (e.g. self-hosted models).
 */
export function findCloudProvider(
  providerType: string | null
): CloudEmbeddingProvider | null {
  if (!providerType) return null;
  return CLOUD_EMBEDDING_PROVIDERS[providerType as EmbeddingProvider] ?? null;
}

export function getEmbeddingProvider(providerType: string | null): {
  icon: IconFunctionComponent;
  displayName: string;
} {
  if (!providerType) return { icon: SvgNomic, displayName: "Self-hosted" };
  return {
    icon: findCloudProvider(providerType)?.icon ?? SvgCpu,
    displayName: getFormattedProviderName(providerType),
  };
}

export function getCurrentModelCopy(
  currentModelName: string
): CloudEmbeddingModel | SelfHostedEmbeddingModel | null {
  const CLOUD_EMBEDDING_PROVIDERS_FLATTENED = Object.values(
    CLOUD_EMBEDDING_PROVIDERS
  ).flatMap((provider) => provider.embedding_models);

  return (
    SELF_HOSTED_MODELS.find((model) => model.model_name === currentModelName) ||
    CLOUD_EMBEDDING_PROVIDERS_FLATTENED.find(
      (model) => model.model_name === currentModelName
    ) ||
    null
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// Image processing
// ═══════════════════════════════════════════════════════════════════════════

export const MAX_IMAGE_SIZE_OPTIONS = ["5", "10", "20", "50", "100"];

// ═══════════════════════════════════════════════════════════════════════════
// Reranking
// ═══════════════════════════════════════════════════════════════════════════

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

// ─── Reranking helpers ───────────────────────────────────────────────────────

export function getTitleForRerankType(type: string) {
  switch (type) {
    case "nomic-ai":
      return "Nomic (recommended)";
    case "intfloat":
      return "Microsoft";
    default:
      return "Open Source";
  }
}

export function getIconForRerankType(type: string) {
  switch (type) {
    case "nomic-ai":
      return <SvgNomic size={40} />;
    case "intfloat":
      return <SvgMicrosoft size={40} />;
    default:
      return <OpenSourceIcon size={40} />;
  }
}
