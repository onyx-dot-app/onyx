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
  CloudBasedEmbeddingProviderName,
  EmbeddingModel,
  EmbeddingProvider,
  EmbeddingProviderName,
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

// ─── Self-hosted embedding providers ────────────────────────────────────────

export const SELF_HOSTED_PROVIDERS: EmbeddingProvider[] = [
  {
    providerName: EmbeddingProviderName.NOMIC,
    icon: SvgNomic,
    docsLink: "https://huggingface.co/nomic-ai",
    embeddingModels: [
      {
        model_name: "nomic-ai/nomic-embed-text-v1",
        model_dim: 768,
        normalize: true,
        query_prefix: "search_query: ",
        passage_prefix: "search_document: ",
        provider_type: null,
        description:
          "Nomic's embedding model specialized for retrieval, similarity, clustering and classification.",
      },
    ],
  },
  {
    providerName: EmbeddingProviderName.MICROSOFT,
    icon: SvgMicrosoft,
    docsLink: "https://huggingface.co/intfloat",
    embeddingModels: [
      {
        model_name: "intfloat/e5-base-v2",
        model_dim: 768,
        normalize: true,
        query_prefix: "query: ",
        passage_prefix: "passage: ",
        provider_type: null,
        description:
          "A smaller and faster model than the default. It is around 2x faster than the default model at the cost of lower search quality.",
      },
      {
        model_name: "intfloat/e5-small-v2",
        model_dim: 384,
        normalize: true,
        query_prefix: "query: ",
        passage_prefix: "passage: ",
        provider_type: null,
        description:
          "The smallest and fastest version of the E5 line of models. If you're running Onyx on a resource constrained system, then this may be a good choice.",
      },
      {
        model_name: "intfloat/multilingual-e5-base",
        model_dim: 768,
        normalize: true,
        query_prefix: "query: ",
        passage_prefix: "passage: ",
        provider_type: null,
        description:
          "For corpora in other languages besides English, this is the one to choose.",
      },
      {
        model_name: "intfloat/multilingual-e5-small",
        model_dim: 384,
        normalize: true,
        query_prefix: "query: ",
        passage_prefix: "passage: ",
        provider_type: null,
        description:
          "For corpora in other languages besides English, as well as being on a resource constrained system, this is the one to choose.",
      },
    ],
  },
];

// ─── Cloud embedding providers ───────────────────────────────────────────────

/**
 * Registry of cloud embedding providers, keyed by {@link EmbeddingProviderName}.
 *
 * This is the single source of truth for cloud embedding providers. Add new
 * entries here when introducing a new provider — the `Record` typing forces
 * exhaustiveness, so a missing entry is a compile-time error.
 */
export const CLOUD_BASED_PROVIDERS: Record<
  CloudBasedEmbeddingProviderName,
  EmbeddingProvider
> = {
  [EmbeddingProviderName.COHERE]: {
    providerName: EmbeddingProviderName.COHERE,
    icon: SvgCohere,
    docsLink: `${DOCS_ADMINS_PATH}/advanced_configs/search_configs`,
    apiLink: "https://dashboard.cohere.ai/api-keys",
    costslink: "https://cohere.com/pricing",
    embeddingModels: [
      {
        provider_type: EmbeddingProviderName.COHERE,
        model_name: "embed-english-v3.0",
        model_dim: 1024,
        normalize: false,
        query_prefix: "",
        passage_prefix: "",
        description:
          "Cohere's English embedding model. Good performance for English-language tasks.",
      },
      {
        provider_type: EmbeddingProviderName.COHERE,
        model_name: "embed-english-light-v3.0",
        model_dim: 384,
        normalize: false,
        query_prefix: "",
        passage_prefix: "",
        description:
          "Cohere's lightweight English embedding model. Faster and more efficient for simpler tasks.",
      },
    ],
  },
  [EmbeddingProviderName.OPENAI]: {
    providerName: EmbeddingProviderName.OPENAI,
    icon: SvgOpenai,
    docsLink: `${DOCS_ADMINS_PATH}/advanced_configs/search_configs`,
    apiLink: "https://platform.openai.com/api-keys",
    costslink: "https://openai.com/pricing",
    embeddingModels: [
      {
        provider_type: EmbeddingProviderName.OPENAI,
        model_name: "text-embedding-3-large",
        model_dim: 3072,
        normalize: false,
        query_prefix: "",
        passage_prefix: "",
        description:
          "OpenAI's large embedding model. Best performance, but more expensive.",
      },
      {
        provider_type: EmbeddingProviderName.OPENAI,
        model_name: "text-embedding-3-small",
        model_dim: 1536,
        normalize: false,
        query_prefix: "",
        passage_prefix: "",
        description:
          "OpenAI's newer, more efficient embedding model. Good balance of performance and cost.",
      },
    ],
  },
  [EmbeddingProviderName.GOOGLE]: {
    providerName: EmbeddingProviderName.GOOGLE,
    icon: SvgGoogle,
    docsLink: `${DOCS_ADMINS_PATH}/advanced_configs/search_configs`,
    apiLink: "https://console.cloud.google.com/apis/credentials",
    costslink: "https://cloud.google.com/vertex-ai/pricing",
    embeddingModels: [
      {
        provider_type: EmbeddingProviderName.GOOGLE,
        model_name: "gemini-embedding-001",
        model_dim: 3072,
        normalize: false,
        query_prefix: "",
        passage_prefix: "",
        description: "Google's Gemini embedding model. Powerful and efficient.",
      },
      {
        provider_type: EmbeddingProviderName.GOOGLE,
        model_name: "text-embedding-005",
        model_dim: 768,
        normalize: false,
        query_prefix: "",
        passage_prefix: "",
        description: "Smaller, lighter-weight embedding model from Google.",
      },
    ],
  },
  [EmbeddingProviderName.VOYAGE]: {
    providerName: EmbeddingProviderName.VOYAGE,
    icon: SvgVoyage,
    docsLink: `${DOCS_ADMINS_PATH}/advanced_configs/search_configs`,
    apiLink: "https://www.voyageai.com/dashboard",
    costslink: "https://www.voyageai.com/pricing",
    deprecated: true,
    embeddingModels: [
      {
        provider_type: EmbeddingProviderName.VOYAGE,
        model_name: "voyage-large-2-instruct",
        model_dim: 1024,
        normalize: false,
        query_prefix: "",
        passage_prefix: "",
        description:
          "Voyage's large embedding model. High performance with instruction fine-tuning.",
      },
      {
        provider_type: EmbeddingProviderName.VOYAGE,
        model_name: "voyage-light-2-instruct",
        model_dim: 1024,
        normalize: false,
        query_prefix: "",
        passage_prefix: "",
        description:
          "Voyage's lightweight embedding model. Good balance of performance and efficiency.",
      },
    ],
  },
  [EmbeddingProviderName.LITELLM]: {
    providerName: EmbeddingProviderName.LITELLM,
    icon: SvgLitellm,
    apiLink: "https://docs.litellm.ai/docs/proxy/quick_start",
    embeddingModels: [],
  },
  [EmbeddingProviderName.AZURE]: {
    providerName: EmbeddingProviderName.AZURE,
    icon: SvgAzure,
    apiLink:
      "https://docs.microsoft.com/en-us/azure/ai-services/openai/how-to/create-resource",
    costslink:
      "https://azure.microsoft.com/en-us/pricing/details/cognitive-services/openai/",
    embeddingModels: [],
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
 * Find the {@link EmbeddingProvider} entry matching `providerType`, or
 * `null` if none matches (e.g. self-hosted models).
 */
export function findCloudProvider(
  providerType: string | null
): EmbeddingProvider | null {
  if (!providerType) return null;
  return (
    CLOUD_BASED_PROVIDERS[providerType as CloudBasedEmbeddingProviderName] ??
    null
  );
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
): EmbeddingModel | null {
  const allModels = [
    ...SELF_HOSTED_PROVIDERS,
    ...Object.values(CLOUD_BASED_PROVIDERS),
  ].flatMap((p) => p.embeddingModels);

  return allModels.find((m) => m.model_name === currentModelName) ?? null;
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
