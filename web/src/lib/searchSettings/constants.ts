import { SvgHardDrive, SvgPlug, SvgServer } from "@opal/icons";
import {
  SvgAzure,
  SvgBifrost,
  SvgCohere,
  SvgGoogle,
  SvgIBM,
  SvgLiteLLM,
  SvgMicrosoft,
  SvgNomic,
  SvgNVIDIA,
  SvgOpenAI,
  SvgVoyage,
} from "@opal/logos";
import {
  EmbeddingProvider,
  EmbeddingProviderName,
} from "@/lib/searchSettings/types";
import { DOCS_ADMINS_PATH } from "@/lib/constants";

// ═══════════════════════════════════════════════════════════════════════════
// Embedding
//
// Mirrors backend/shared_configs/embedding_models.py, and
// test_web_embedding_model_registry_parity.py pins the two together. Never
// remove or rename an entry: mark it `legacy`. List selectable models first in
// each group.
// ═══════════════════════════════════════════════════════════════════════════

export const CLOUD_BASED_PROVIDERS: EmbeddingProvider[] = [
  {
    providerName: EmbeddingProviderName.COHERE,
    displayName: "Cohere",
    icon: SvgCohere,
    docsLink: `${DOCS_ADMINS_PATH}/advanced_configs/search_configs`,
    apiLink: "https://dashboard.cohere.ai/api-keys",
    costslink: "https://cohere.com/pricing",
    embeddingModels: [
      {
        modelName: "embed-v5.0-pro",
        modelDim: 2048,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        descriptionKey: "modelDescriptions.cohereEmbedV5Pro",
      },
      {
        modelName: "embed-v5.0-fast",
        modelDim: 2048,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        descriptionKey: "modelDescriptions.cohereEmbedV5Fast",
      },
      {
        modelName: "embed-english-v3.0",
        modelDim: 1024,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        descriptionKey: "modelDescriptions.cohereEmbedEnglishV3",
        legacy: true,
      },
      {
        modelName: "embed-english-light-v3.0",
        modelDim: 384,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        descriptionKey: "modelDescriptions.cohereEmbedEnglishLightV3",
        legacy: true,
      },
      {
        modelName: "embed-v4.0",
        modelDim: 1536,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        descriptionKey: "modelDescriptions.cohereEmbedV4",
        legacy: true,
      },
    ],
  },
  {
    providerName: EmbeddingProviderName.OPENAI,
    displayName: "OpenAI",
    icon: SvgOpenAI,
    docsLink: `${DOCS_ADMINS_PATH}/advanced_configs/search_configs`,
    apiLink: "https://platform.openai.com/api-keys",
    costslink: "https://openai.com/pricing",
    embeddingModels: [
      {
        modelName: "text-embedding-3-large",
        modelDim: 3072,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        descriptionKey: "modelDescriptions.openaiTextEmbedding3Large",
      },
      {
        modelName: "text-embedding-3-small",
        modelDim: 1536,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        descriptionKey: "modelDescriptions.openaiTextEmbedding3Small",
      },
    ],
  },
  {
    providerName: EmbeddingProviderName.GOOGLE,
    displayName: "Google",
    icon: SvgGoogle,
    docsLink: `${DOCS_ADMINS_PATH}/advanced_configs/search_configs`,
    apiLink: "https://console.cloud.google.com/apis/credentials",
    costslink: "https://cloud.google.com/vertex-ai/pricing",
    embeddingModels: [
      {
        modelName: "gemini-embedding-2",
        modelDim: 3072,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        descriptionKey: "modelDescriptions.googleGeminiEmbedding2",
      },
      {
        modelName: "gemini-embedding-001",
        modelDim: 3072,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        descriptionKey: "modelDescriptions.googleGeminiEmbedding001",
        legacy: true,
      },
      {
        modelName: "text-embedding-005",
        modelDim: 768,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        descriptionKey: "modelDescriptions.googleTextEmbedding005",
        legacy: true,
      },
      {
        modelName: "gemini-embedding-2-preview",
        modelDim: 3072,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        descriptionKey: "modelDescriptions.googleGeminiEmbedding2Preview",
        legacy: true,
      },
      {
        modelName: "text-embedding-004",
        modelDim: 768,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        legacy: true,
      },
      {
        modelName: "textembedding-gecko@003",
        modelDim: 768,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        legacy: true,
      },
    ],
  },
  {
    providerName: EmbeddingProviderName.VOYAGE,
    displayName: "Voyage",
    icon: SvgVoyage,
    docsLink: `${DOCS_ADMINS_PATH}/advanced_configs/search_configs`,
    apiLink: "https://www.voyageai.com/dashboard",
    costslink: "https://www.voyageai.com/pricing",
    embeddingModels: [
      {
        modelName: "voyage-4-large",
        modelDim: 1024,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        descriptionKey: "modelDescriptions.voyage4Large",
      },
      {
        modelName: "voyage-4",
        modelDim: 1024,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        descriptionKey: "modelDescriptions.voyage4",
      },
      {
        modelName: "voyage-4-lite",
        modelDim: 1024,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        descriptionKey: "modelDescriptions.voyage4Lite",
      },
      {
        modelName: "voyage-large-2-instruct",
        modelDim: 1024,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        descriptionKey: "modelDescriptions.voyageLarge2Instruct",
        legacy: true,
      },
      {
        modelName: "voyage-light-2-instruct",
        modelDim: 1024,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        descriptionKey: "modelDescriptions.voyageLight2Instruct",
        legacy: true,
      },
    ],
  },
  // Bring-your-own providers: no registry models. The admin enters the model
  // spec in the connect modal. See `isBringYourOwnProvider`.
  {
    providerName: EmbeddingProviderName.LITELLM,
    displayName: "LiteLLM",
    icon: SvgLiteLLM,
    apiLink: "https://docs.litellm.ai/docs/proxy/quick_start",
    embeddingModels: [],
  },
  {
    providerName: EmbeddingProviderName.AZURE,
    displayName: "Azure",
    icon: SvgAzure,
    apiLink:
      "https://docs.microsoft.com/en-us/azure/ai-services/openai/how-to/create-resource",
    costslink:
      "https://azure.microsoft.com/en-us/pricing/details/cognitive-services/openai/",
    embeddingModels: [],
  },
  {
    providerName: EmbeddingProviderName.BIFROST,
    displayName: "Bifrost",
    icon: SvgBifrost,
    apiLink:
      "https://docs.getbifrost.ai/providers/supported-providers/overview",
    embeddingModels: [],
  },
  {
    providerName: EmbeddingProviderName.OPENAI_COMPATIBLE,
    displayName: "OpenAI-Compatible",
    icon: SvgPlug,
    apiLink: "https://platform.openai.com/docs/api-reference/embeddings/create",
    embeddingModels: [],
  },
];

export const SELF_HOSTED_PROVIDERS: EmbeddingProvider[] = [
  {
    providerName: EmbeddingProviderName.IBM,
    displayName: "IBM",
    icon: SvgIBM,
    docsLink: "https://huggingface.co/ibm-granite",
    embeddingModels: [
      {
        modelName: "ibm-granite/granite-embedding-97m-multilingual-r2",
        modelDim: 384,
        normalize: true,
        queryPrefix: "",
        passagePrefix: "",
        descriptionKey: "modelDescriptions.graniteEmbedding97mMultilingualR2",
      },
    ],
  },
  {
    providerName: EmbeddingProviderName.VOYAGE_SELF_HOSTED,
    displayName: "Voyage AI",
    icon: SvgVoyage,
    docsLink: "https://huggingface.co/voyageai",
    embeddingModels: [
      {
        modelName: "voyageai/voyage-4-nano",
        modelDim: 2048,
        normalize: true,
        queryPrefix:
          "Represent the query for retrieving supporting documents: ",
        passagePrefix: "Represent the document for retrieval: ",
        descriptionKey: "modelDescriptions.voyage4Nano",
      },
    ],
  },
  {
    providerName: EmbeddingProviderName.NVIDIA,
    displayName: "NVIDIA",
    icon: SvgNVIDIA,
    docsLink: "https://huggingface.co/nvidia",
    embeddingModels: [
      {
        modelName: "nvidia/Nemotron-3-Embed-1B-BF16",
        modelDim: 2048,
        normalize: true,
        queryPrefix: "query: ",
        passagePrefix: "passage: ",
        descriptionKey: "modelDescriptions.nemotron3Embed1b",
        gpuRecommended: true,
      },
    ],
  },
  {
    providerName: EmbeddingProviderName.NOMIC,
    displayName: "Nomic",
    icon: SvgNomic,
    docsLink: "https://huggingface.co/nomic-ai",
    embeddingModels: [
      {
        modelName: "nomic-ai/nomic-embed-text-v1",
        modelDim: 768,
        normalize: true,
        queryPrefix: "search_query: ",
        passagePrefix: "search_document: ",
        descriptionKey: "modelDescriptions.nomicEmbedTextV1",
        legacy: true,
      },
    ],
  },
  {
    providerName: EmbeddingProviderName.MICROSOFT,
    displayName: "Microsoft",
    icon: SvgMicrosoft,
    docsLink: "https://huggingface.co/intfloat",
    embeddingModels: [
      {
        modelName: "intfloat/e5-base-v2",
        modelDim: 768,
        normalize: true,
        queryPrefix: "query: ",
        passagePrefix: "passage: ",
        descriptionKey: "modelDescriptions.e5BaseV2",
        legacy: true,
      },
      {
        modelName: "intfloat/e5-small-v2",
        modelDim: 384,
        normalize: true,
        queryPrefix: "query: ",
        passagePrefix: "passage: ",
        descriptionKey: "modelDescriptions.e5SmallV2",
        legacy: true,
      },
      {
        modelName: "intfloat/multilingual-e5-base",
        modelDim: 768,
        normalize: true,
        queryPrefix: "query: ",
        passagePrefix: "passage: ",
        descriptionKey: "modelDescriptions.multilingualE5Base",
        legacy: true,
      },
      {
        modelName: "intfloat/multilingual-e5-small",
        modelDim: 384,
        normalize: true,
        queryPrefix: "query: ",
        passagePrefix: "passage: ",
        descriptionKey: "modelDescriptions.multilingualE5Small",
        legacy: true,
      },
    ],
  },
  {
    providerName: EmbeddingProviderName.GTE,
    displayName: "GTE",
    icon: SvgServer,
    docsLink: "https://huggingface.co/thenlper",
    embeddingModels: [
      {
        modelName: "thenlper/gte-small",
        modelDim: 384,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        legacy: true,
      },
    ],
  },
];

/**
 * Synthetic provider used by the "Add Custom Model" flow. Not a real provider —
 * its `providerName` never reaches the backend (custom self-hosted models are
 * persisted with `provider_type=null` like other self-hosted models). Exists so
 * the modal can be dispatched through `ProviderCredentialsModal` like every
 * other provider.
 */
export const CUSTOM_PROVIDER: EmbeddingProvider = {
  providerName: EmbeddingProviderName.CUSTOM,
  displayName: "Custom Model",
  icon: SvgHardDrive,
  embeddingModels: [],
};

// ═══════════════════════════════════════════════════════════════════════════
// Image processing
// ═══════════════════════════════════════════════════════════════════════════

/** Mirror the `*IMAGE_ANALYSIS_MAX_SIZE_MB` constants on the backend. */
export const DEFAULT_IMAGE_ANALYSIS_MAX_SIZE_MB = 20;
export const MAX_IMAGE_ANALYSIS_MAX_SIZE_MB = 100;

/** Mirror the `*EMBEDDING_RATE_LIMIT*` constants on the backend. */
export const DEFAULT_EMBEDDING_RATE_LIMIT_PERIOD_SECONDS = 60;
export const MAX_EMBEDDING_RATE_LIMIT_REQUESTS = 100_000;
export const MAX_EMBEDDING_RATE_LIMIT_PERIOD_SECONDS = 24 * 60 * 60;
