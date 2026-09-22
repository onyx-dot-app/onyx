import { SvgHardDrive } from "@opal/icons";
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
import {
  EmbeddingProvider,
  EmbeddingProviderName,
} from "@/lib/searchSettings/types";
import { DOCS_ADMINS_PATH } from "@/lib/constants";

// ═══════════════════════════════════════════════════════════════════════════
// Embedding
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
        modelName: "embed-english-v3.0",
        modelDim: 1024,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        descriptionKey: "modelDescriptions.cohereEmbedEnglishV3",
      },
      {
        modelName: "embed-english-light-v3.0",
        modelDim: 384,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        descriptionKey: "modelDescriptions.cohereEmbedEnglishLightV3",
      },
      {
        modelName: "embed-v4.0",
        modelDim: 1536,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        descriptionKey: "modelDescriptions.cohereEmbedV4",
      },
    ],
  },
  {
    providerName: EmbeddingProviderName.OPENAI,
    displayName: "OpenAI",
    icon: SvgOpenai,
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
        modelName: "gemini-embedding-001",
        modelDim: 3072,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        descriptionKey: "modelDescriptions.googleGeminiEmbedding001",
      },
      {
        modelName: "text-embedding-005",
        modelDim: 768,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        descriptionKey: "modelDescriptions.googleTextEmbedding005",
      },
      {
        modelName: "gemini-embedding-2",
        modelDim: 3072,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        descriptionKey: "modelDescriptions.googleGeminiEmbedding2",
      },
      {
        modelName: "gemini-embedding-2-preview",
        modelDim: 3072,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        descriptionKey: "modelDescriptions.googleGeminiEmbedding2Preview",
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
    deprecated: true,
    embeddingModels: [
      {
        modelName: "voyage-large-2-instruct",
        modelDim: 1024,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        descriptionKey: "modelDescriptions.voyageLarge2Instruct",
      },
      {
        modelName: "voyage-light-2-instruct",
        modelDim: 1024,
        normalize: false,
        queryPrefix: "",
        passagePrefix: "",
        descriptionKey: "modelDescriptions.voyageLight2Instruct",
      },
    ],
  },
  {
    providerName: EmbeddingProviderName.LITELLM,
    displayName: "LiteLLM",
    icon: SvgLitellm,
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
];

export const SELF_HOSTED_PROVIDERS: EmbeddingProvider[] = [
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
      },
      {
        modelName: "intfloat/e5-small-v2",
        modelDim: 384,
        normalize: true,
        queryPrefix: "query: ",
        passagePrefix: "passage: ",
        descriptionKey: "modelDescriptions.e5SmallV2",
      },
      {
        modelName: "intfloat/multilingual-e5-base",
        modelDim: 768,
        normalize: true,
        queryPrefix: "query: ",
        passagePrefix: "passage: ",
        descriptionKey: "modelDescriptions.multilingualE5Base",
      },
      {
        modelName: "intfloat/multilingual-e5-small",
        modelDim: 384,
        normalize: true,
        queryPrefix: "query: ",
        passagePrefix: "passage: ",
        descriptionKey: "modelDescriptions.multilingualE5Small",
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

export const MAX_IMAGE_SIZE_OPTIONS = ["5", "10", "20", "50", "100"];

/** Mirrors `DEFAULT_IMAGE_ANALYSIS_MAX_SIZE_MB` on the backend. */
export const DEFAULT_IMAGE_ANALYSIS_MAX_SIZE_MB = 20;
