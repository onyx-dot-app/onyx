import {
  AzureIcon,
  CohereIcon,
  GoogleIcon,
  IconProps,
  LiteLLMIcon,
  MicrosoftIcon,
  NomicIcon,
  OpenAIISVG,
  OpenSourceIcon,
  VoyageIconSVG,
} from "@/components/icons/icons";

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
  icon: ({ size, className }: IconProps) => JSX.Element;
  description: string;
  apiLink: string;
  costslink?: string;

  // Relationships
  embedding_models: CloudEmbeddingModel[];
  default_model?: CloudEmbeddingModel;
}

// Embedding Models
export interface EmbeddingModelDescriptor {
  id?: number;
  model_name: string;
  model_dim: number;
  normalize: boolean;
  query_prefix: string;
  passage_prefix: string;
  provider_type: EmbeddingProvider | null;
  description: string;
  api_key: string | null;
  api_url: string | null;
  api_version?: string | null;
  deployment_name?: string | null;
  index_name: string | null;
  background_reindex_enabled?: boolean;
}

export interface CloudEmbeddingModel extends EmbeddingModelDescriptor {
  pricePerMillion: number;
}

export interface HostedEmbeddingModel extends EmbeddingModelDescriptor {
  link?: string;
  isDefault?: boolean;
}

// Responses
export interface FullEmbeddingModelResponse {
  current_model_name: string;
  secondary_model_name: string | null;
}

export interface CloudEmbeddingProviderFull extends CloudEmbeddingProvider {
  configured?: boolean;
}

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

export const LITELLM_CLOUD_PROVIDER: CloudEmbeddingProvider = {
  provider_type: EmbeddingProvider.LITELLM,
  website: "https://github.com/BerriAI/litellm",
  icon: LiteLLMIcon,
  description: "Open-source library to call LLM APIs using OpenAI format",
  apiLink: "https://docs.litellm.ai/docs/proxy/quick_start",
  embedding_models: [], // No default embedding models
};

export const AZURE_CLOUD_PROVIDER: CloudEmbeddingProvider = {
  provider_type: EmbeddingProvider.AZURE,
  website:
    "https://azure.microsoft.com/en-us/products/cognitive-services/openai/",
  icon: AzureIcon,
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
    icon: CohereIcon,
    docsLink: "https://docs.onyx.app/admin/advanced_configs/search_configs",
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
    icon: OpenAIISVG,
    description: "AI industry leader known for ChatGPT and DALL-E",
    apiLink: "https://platform.openai.com/api-keys",
    docsLink: "https://docs.onyx.app/admin/advanced_configs/search_configs",
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
    icon: GoogleIcon,
    docsLink: "https://docs.onyx.app/admin/advanced_configs/search_configs",
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
    icon: VoyageIconSVG,
    description: "Advanced NLP research startup born from Stanford AI Labs",
    docsLink: "https://docs.onyx.app/admin/advanced_configs/search_configs",
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

export const getFormattedProviderName = (providerType: string | null) => {
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
};

export const getTitleForRerankType = (type: string) => {
  switch (type) {
    case "nomic-ai":
      return "Nomic (recommended)";
    case "intfloat":
      return "Microsoft";
    default:
      return "Open Source";
  }
};

export const getIconForRerankType = (type: string) => {
  switch (type) {
    case "nomic-ai":
      return <NomicIcon size={40} />;
    case "intfloat":
      return <MicrosoftIcon size={40} />;
    default:
      return <OpenSourceIcon size={40} />;
  }
};

export const INVALID_OLD_MODEL = "thenlper/gte-small";

export function checkModelNameIsValid(
  modelName: string | undefined | null
): boolean {
  return !!modelName && modelName !== INVALID_OLD_MODEL;
}
