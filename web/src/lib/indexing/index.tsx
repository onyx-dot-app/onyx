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
  HostedEmbeddingModel,
  RerankerProvider,
  RerankingModel,
} from "@/lib/indexing/interfaces";
import { DOCS_ADMINS_PATH } from "@/lib/constants";

// ─── Backend URLs ────────────────────────────────────────────────────────────

export const EMBEDDING_PROVIDERS_ADMIN_URL =
  "/api/admin/embedding/embedding-provider";

export const EMBEDDING_MODELS_ADMIN_URL = "/api/admin/embedding";

// ─── UI options ──────────────────────────────────────────────────────────────

export const MAX_IMAGE_SIZE_OPTIONS = ["5", "10", "20", "50", "100"];

// ─── Hosted (self-hosted) embedding models ───────────────────────────────────

export const AVAILABLE_MODELS: HostedEmbeddingModel[] = [
  {
    model_name: "nomic-ai/nomic-embed-text-v1",
    model_dim: 768,
    normalize: true,
    description:
      "The recommended default for most situations. If you aren't sure which model to use, this is probably the one.",
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

export const LITELLM_CLOUD_PROVIDER: CloudEmbeddingProvider = {
  provider_type: EmbeddingProvider.LITELLM,
  website: "https://github.com/BerriAI/litellm",
  icon: SvgLitellm,
  description: "Open-source library to call LLM APIs using OpenAI format",
  apiLink: "https://docs.litellm.ai/docs/proxy/quick_start",
  embedding_models: [], // No default embedding models
};

export const AZURE_CLOUD_PROVIDER: CloudEmbeddingProvider = {
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
};

export const AVAILABLE_CLOUD_PROVIDERS: CloudEmbeddingProvider[] = [
  {
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
  {
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

  {
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
  {
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
];

// ─── Reranking models ────────────────────────────────────────────────────────

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

// ─── Helpers ─────────────────────────────────────────────────────────────────

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

export function getCurrentModelCopy(
  currentModelName: string
): CloudEmbeddingModel | HostedEmbeddingModel | null {
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
}

// ─── Provider lookup (icon + display name) ───────────────────────────────────

export interface EmbeddingProviderEntry {
  icon: IconFunctionComponent;
  displayName: string;
}

const PROVIDERS: Record<string, EmbeddingProviderEntry> = {
  [EmbeddingProvider.OPENAI]: { icon: SvgOpenai, displayName: "OpenAI" },
  [EmbeddingProvider.COHERE]: { icon: SvgCohere, displayName: "Cohere" },
  [EmbeddingProvider.VOYAGE]: { icon: SvgVoyage, displayName: "Voyage AI" },
  [EmbeddingProvider.GOOGLE]: { icon: SvgGoogle, displayName: "Google" },
  [EmbeddingProvider.LITELLM]: { icon: SvgLitellm, displayName: "LiteLLM" },
  [EmbeddingProvider.AZURE]: { icon: SvgAzure, displayName: "Azure" },
};

const SELF_HOSTED_ENTRY: EmbeddingProviderEntry = {
  icon: SvgNomic,
  displayName: "Self-hosted",
};

const DEFAULT_ENTRY: EmbeddingProviderEntry = {
  icon: SvgCpu,
  displayName: "Self-hosted",
};

export function getEmbeddingProvider(
  providerType: string | null
): EmbeddingProviderEntry {
  if (!providerType) return SELF_HOSTED_ENTRY;
  return (
    PROVIDERS[providerType] ?? {
      ...DEFAULT_ENTRY,
      displayName: providerType.charAt(0).toUpperCase() + providerType.slice(1),
    }
  );
}

const ALL_CLOUD_PROVIDERS: CloudEmbeddingProvider[] = [
  ...AVAILABLE_CLOUD_PROVIDERS,
  LITELLM_CLOUD_PROVIDER,
  AZURE_CLOUD_PROVIDER,
];

/**
 * Find the {@link CloudEmbeddingProvider} entry matching `providerType`, or
 * `null` if none matches (e.g. self-hosted models).
 */
export function findCloudProvider(
  providerType: string | null
): CloudEmbeddingProvider | null {
  if (!providerType) return null;
  return (
    ALL_CLOUD_PROVIDERS.find((p) => p.provider_type === providerType) ?? null
  );
}
