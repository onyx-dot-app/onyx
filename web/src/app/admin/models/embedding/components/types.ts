import {
  CohereIcon,
  GoogleIcon,
  IconProps,
  OpenAIIcon,
  VoyageIcon,
} from "@/components/icons/icons";

// Cloud Provider (not needed for hosted ones)

export interface CloudEmbeddingProvider {
  id: number;
  name: string;
  api_key?: string;
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
  model_name: string;
  model_dim: number;
  normalize: boolean;
  query_prefix: string;
  passage_prefix: string;
  cloud_provider_name?: string | null;
  description: string;
}

export interface CloudEmbeddingModel extends EmbeddingModelDescriptor {
  cloud_provider_name: string | null;
  pricePerMillion: number;
  enabled?: boolean;
  mtebScore: number;
  maxContext: number;
}

export interface HostedEmbeddingModel extends EmbeddingModelDescriptor {
  link?: string;
  model_dim: number;
  normalize: boolean;
  query_prefix: string;
  passage_prefix: string;
  isDefault?: boolean;
}

// Responses
export interface FullEmbeddingModelResponse {
  current_model_name: string;
  secondary_model_name: string | null;
}

export interface CloudEmbeddingProviderFull extends CloudEmbeddingProvider {
  configured: boolean;
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
  },
  {
    model_name: "intfloat/e5-small-v2",
    model_dim: 384,
    normalize: true,
    description:
      "The smallest and fastest version of the E5 line of models. If you're running Danswer on a resource constrained system, then this may be a good choice.",
    link: "https://huggingface.co/intfloat/e5-small-v2",
    query_prefix: "query: ",
    passage_prefix: "passage: ",
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
  },
];

export const AVAILABLE_CLOUD_PROVIDERS: CloudEmbeddingProvider[] = [
  {
    id: 0,
    name: "OpenAI",
    website: "https://openai.com",
    icon: OpenAIIcon,
    description: "AI industry leader known for ChatGPT and DALL-E",
    apiLink: "https://platform.openai.com/api-keys",
    docsLink:
      "https://docs.danswer.dev/guides/embedding_providers#openai-models",
    costslink: "https://openai.com/pricing",
    embedding_models: [
      {
        model_name: "text-embedding-3-large",
        cloud_provider_name: "OpenAI",
        description:
          "OpenAI's large embedding model. Best performance, but more expensive.",
        pricePerMillion: 0.13,
        model_dim: 3072,
        normalize: false,
        query_prefix: "",
        passage_prefix: "",
        mtebScore: 64.6,
        maxContext: 8191,
        enabled: false,
      },
      {
        model_name: "text-embedding-3-small",
        cloud_provider_name: "OpenAI",
        model_dim: 1536,
        normalize: false,
        query_prefix: "",
        passage_prefix: "",
        description:
          "OpenAI's newer, more efficient embedding model. Good balance of performance and cost.",
        pricePerMillion: 0.02,
        enabled: false,
        mtebScore: 62.3,
        maxContext: 8191,
      },
    ],
  },
  {
    id: 1,
    name: "Cohere",
    website: "https://cohere.ai",
    icon: CohereIcon,
    docsLink:
      "https://docs.danswer.dev/guides/embedding_providers#cohere-models",
    description:
      "AI company specializing in NLP models for various text-based tasks",
    apiLink: "https://dashboard.cohere.ai/api-keys",
    costslink: "https://cohere.com/pricing",
    embedding_models: [
      {
        model_name: "embed-english-v3.0",
        cloud_provider_name: "Cohere",
        description:
          "Cohere's English embedding model. Good performance for English-language tasks.",
        pricePerMillion: 0.1,
        mtebScore: 64.5,
        maxContext: 512,
        enabled: false,
        model_dim: 1024,
        normalize: false,
        query_prefix: "",
        passage_prefix: "",
      },
      {
        model_name: "embed-english-light-v3.0",
        cloud_provider_name: "Cohere",
        description:
          "Cohere's lightweight English embedding model. Faster and more efficient for simpler tasks.",
        pricePerMillion: 0.1,
        mtebScore: 62,
        maxContext: 512,
        enabled: false,
        model_dim: 384,
        normalize: false,
        query_prefix: "",
        passage_prefix: "",
      },
    ],
  },

  {
    id: 2,
    name: "Google",
    website: "https://ai.google",
    icon: GoogleIcon,
    docsLink:
      "https://docs.danswer.dev/guides/embedding_providers#vertex-ai-google-model",
    description:
      "Offers a wide range of AI services including language and vision models",
    apiLink: "https://console.cloud.google.com/apis/credentials",
    costslink: "https://cloud.google.com/vertex-ai/pricing",
    embedding_models: [
      {
        cloud_provider_name: "Google",
        model_name: "text-embedding-004",
        description: "Google's most recent text embedding model.",
        pricePerMillion: 0.025,
        mtebScore: 66.31,
        maxContext: 2048,
        enabled: false,
        model_dim: 768,
        normalize: false,
        query_prefix: "",
        passage_prefix: "",
      },
      {
        cloud_provider_name: "Google",
        model_name: "textembedding-gecko@003",
        description: "Google's Gecko embedding model. Powerful and efficient.",
        pricePerMillion: 0.025,
        mtebScore: 66.31,
        maxContext: 2048,
        enabled: false,
        model_dim: 768,
        normalize: false,
        query_prefix: "",
        passage_prefix: "",
      },
    ],
  },
  {
    id: 3,
    name: "Voyage",
    website: "https://www.voyageai.com",
    icon: VoyageIcon,
    description: "Advanced NLP research startup born from Stanford AI Labs",
    docsLink:
      "https://docs.danswer.dev/guides/embedding_providers#voyage-models",
    apiLink: "https://www.voyageai.com/dashboard",
    costslink: "https://www.voyageai.com/pricing",
    embedding_models: [
      {
        cloud_provider_name: "Voyage",
        model_name: "voyage-large-2-instruct",
        description:
          "Voyage's large embedding model. High performance with instruction fine-tuning.",
        pricePerMillion: 0.12,
        mtebScore: 68.28,
        maxContext: 4000,
        enabled: false,
        model_dim: 1024,
        normalize: false,
        query_prefix: "",
        passage_prefix: "",
      },
      {
        cloud_provider_name: "Voyage",
        model_name: "voyage-light-2-instruct",
        description:
          "Voyage's lightweight embedding model. Good balance of performance and efficiency.",
        pricePerMillion: 0.12,
        mtebScore: 67.13,
        maxContext: 16000,
        enabled: false,
        model_dim: 1024,
        normalize: false,
        query_prefix: "",
        passage_prefix: "",
      },
    ],
  },
];

export const INVALID_OLD_MODEL = "thenlper/gte-small";

export function checkModelNameIsValid(
  modelName: string | undefined | null
): boolean {
  return !!modelName && modelName !== INVALID_OLD_MODEL;
}
