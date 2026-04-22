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
        modelName: "nomic-ai/nomic-embed-text-v1",
        modelDim: 768,
        normalize: true,
        queryPrefix: "search_query: ",
        passagePrefix: "search_document: ",
        providerType: null,
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
        modelName: "intfloat/e5-base-v2",
        modelDim: 768,
        normalize: true,
        queryPrefix: "query: ",
        passagePrefix: "passage: ",
        providerType: null,
        description:
          "A smaller and faster model than the default. It is around 2x faster than the default model at the cost of lower search quality.",
      },
      {
        modelName: "intfloat/e5-small-v2",
        modelDim: 384,
        normalize: true,
        queryPrefix: "query: ",
        passagePrefix: "passage: ",
        providerType: null,
        description:
          "The smallest and fastest version of the E5 line of models. If you're running Onyx on a resource constrained system, then this may be a good choice.",
      },
      {
        modelName: "intfloat/multilingual-e5-base",
        modelDim: 768,
        normalize: true,
        queryPrefix: "query: ",
        passagePrefix: "passage: ",
        providerType: null,
        description:
          "For corpora in other languages besides English, this is the one to choose.",
      },
      {
        modelName: "intfloat/multilingual-e5-small",
        modelDim: 384,
        normalize: true,
        queryPrefix: "query: ",
        passagePrefix: "passage: ",
        providerType: null,
        description:
          "For corpora in other languages besides English, as well as being on a resource constrained system, this is the one to choose.",
      },
    ],
  },
];

export const CLOUD_BASED_PROVIDERS: EmbeddingProvider[] = [
  {
    providerName: EmbeddingProviderName.COHERE,
    icon: SvgCohere,
    docsLink: `${DOCS_ADMINS_PATH}/advanced_configs/search_configs`,
    apiLink: "https://dashboard.cohere.ai/api-keys",
    costslink: "https://cohere.com/pricing",
    embeddingModels: [
      {
        providerType: EmbeddingProviderName.COHERE,
        modelName: "embed-english-v3.0",
        modelDim: 1024,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        description:
          "Cohere's English embedding model. Good performance for English-language tasks.",
      },
      {
        providerType: EmbeddingProviderName.COHERE,
        modelName: "embed-english-light-v3.0",
        modelDim: 384,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        description:
          "Cohere's lightweight English embedding model. Faster and more efficient for simpler tasks.",
      },
    ],
  },
  {
    providerName: EmbeddingProviderName.OPENAI,
    icon: SvgOpenai,
    docsLink: `${DOCS_ADMINS_PATH}/advanced_configs/search_configs`,
    apiLink: "https://platform.openai.com/api-keys",
    costslink: "https://openai.com/pricing",
    embeddingModels: [
      {
        providerType: EmbeddingProviderName.OPENAI,
        modelName: "text-embedding-3-large",
        modelDim: 3072,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        description:
          "OpenAI's large embedding model. Best performance, but more expensive.",
      },
      {
        providerType: EmbeddingProviderName.OPENAI,
        modelName: "text-embedding-3-small",
        modelDim: 1536,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        description:
          "OpenAI's newer, more efficient embedding model. Good balance of performance and cost.",
      },
    ],
  },
  {
    providerName: EmbeddingProviderName.GOOGLE,
    icon: SvgGoogle,
    docsLink: `${DOCS_ADMINS_PATH}/advanced_configs/search_configs`,
    apiLink: "https://console.cloud.google.com/apis/credentials",
    costslink: "https://cloud.google.com/vertex-ai/pricing",
    embeddingModels: [
      {
        providerType: EmbeddingProviderName.GOOGLE,
        modelName: "gemini-embedding-001",
        modelDim: 3072,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        description: "Google's Gemini embedding model. Powerful and efficient.",
      },
      {
        providerType: EmbeddingProviderName.GOOGLE,
        modelName: "text-embedding-005",
        modelDim: 768,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        description: "Smaller, lighter-weight embedding model from Google.",
      },
    ],
  },
  {
    providerName: EmbeddingProviderName.VOYAGE,
    icon: SvgVoyage,
    docsLink: `${DOCS_ADMINS_PATH}/advanced_configs/search_configs`,
    apiLink: "https://www.voyageai.com/dashboard",
    costslink: "https://www.voyageai.com/pricing",
    deprecated: true,
    embeddingModels: [
      {
        providerType: EmbeddingProviderName.VOYAGE,
        modelName: "voyage-large-2-instruct",
        modelDim: 1024,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        description:
          "Voyage's large embedding model. High performance with instruction fine-tuning.",
      },
      {
        providerType: EmbeddingProviderName.VOYAGE,
        modelName: "voyage-light-2-instruct",
        modelDim: 1024,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        description:
          "Voyage's lightweight embedding model. Good balance of performance and efficiency.",
      },
    ],
  },
  {
    providerName: EmbeddingProviderName.LITELLM,
    icon: SvgLitellm,
    apiLink: "https://docs.litellm.ai/docs/proxy/quick_start",
    embeddingModels: [],
  },
  {
    providerName: EmbeddingProviderName.AZURE,
    icon: SvgAzure,
    apiLink:
      "https://docs.microsoft.com/en-us/azure/ai-services/openai/how-to/create-resource",
    costslink:
      "https://azure.microsoft.com/en-us/pricing/details/cognitive-services/openai/",
    embeddingModels: [],
  },
];

// ─── Embedding helpers ───────────────────────────────────────────────────────

export function getFormattedProviderName(
  providerType: EmbeddingProviderName | null
): string {
  if (!providerType) return "Self-hosted";

  switch (providerType) {
    case EmbeddingProviderName.OPENAI:
      return "OpenAI";
    case EmbeddingProviderName.COHERE:
      return "Cohere";
    case EmbeddingProviderName.VOYAGE:
      return "Voyage AI";
    case EmbeddingProviderName.GOOGLE:
      return "Google";
    case EmbeddingProviderName.LITELLM:
      return "LiteLLM";
    case EmbeddingProviderName.AZURE:
      return "Azure";
    case EmbeddingProviderName.NOMIC:
      return "Nomic";
    case EmbeddingProviderName.MICROSOFT:
      return "Microsoft";
  }
}

/**
 * Find the {@link EmbeddingProvider} entry matching `providerType`, or
 * `null` if none matches (e.g. self-hosted models).
 */
export function findCloudProvider(
  providerType: EmbeddingProviderName | null
): EmbeddingProvider | null {
  if (!providerType) return null;
  return (
    CLOUD_BASED_PROVIDERS.find((p) => p.providerName === providerType) ?? null
  );
}

export function getEmbeddingProvider(
  providerType: EmbeddingProviderName | null
): {
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
    ...CLOUD_BASED_PROVIDERS,
  ].flatMap((p) => p.embeddingModels);

  return allModels.find((m) => m.modelName === currentModelName) ?? null;
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
