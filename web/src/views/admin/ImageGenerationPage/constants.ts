/**
 * Message key of a provider blurb, inside the `admin.imageGeneration`
 * namespace. Held as a key (not copy) so the catalog stays the single source
 * of the English text while the registry stays a plain module.
 */
export type ImageProviderDescriptionKey =
  | "providers.openaiGptImage2.description"
  | "providers.openaiGptImage15.description"
  | "providers.openaiGptImage1.description"
  | "providers.azureGptImage2.description"
  | "providers.azureGptImage15.description"
  | "providers.azureGptImage1.description"
  | "providers.gemini25FlashImage.description"
  | "providers.gemini3ProImage.description"
  | "providers.gemini3ProImagePreview.description";

export interface ImageProvider {
  image_provider_id: string; // Static unique key for UI-DB mapping
  model_name: string; // Actual model name for LLM API
  provider_name: string;
  title: string;
  descriptionKey: ImageProviderDescriptionKey;
  deprecated?: boolean; // Hidden unless already connected (model no longer offered upstream)
}

export interface ProviderGroup {
  // Vendor name — a proper noun, so it is not translated.
  name: string;
  providers: ImageProvider[];
}

export const IMAGE_PROVIDER_GROUPS: ProviderGroup[] = [
  {
    name: "OpenAI",
    providers: [
      {
        image_provider_id: "openai_gpt_image_2",
        model_name: "gpt-image-2",
        provider_name: "openai",
        title: "GPT Image 2",
        descriptionKey: "providers.openaiGptImage2.description",
      },
      {
        image_provider_id: "openai_gpt_image_1_5",
        model_name: "gpt-image-1.5",
        provider_name: "openai",
        title: "GPT Image 1.5",
        descriptionKey: "providers.openaiGptImage15.description",
      },
      {
        image_provider_id: "openai_gpt_image_1",
        model_name: "gpt-image-1",
        provider_name: "openai",
        title: "GPT Image 1",
        descriptionKey: "providers.openaiGptImage1.description",
      },
    ],
  },
  {
    name: "Azure OpenAI",
    providers: [
      {
        image_provider_id: "azure_gpt_image_2",
        model_name: "", // Extracted from deployment in target URI
        provider_name: "azure",
        title: "Azure OpenAI GPT Image 2",
        descriptionKey: "providers.azureGptImage2.description",
      },
      {
        image_provider_id: "azure_gpt_image_1_5",
        model_name: "", // Extracted from deployment in target URI
        provider_name: "azure",
        title: "Azure OpenAI GPT Image 1.5",
        descriptionKey: "providers.azureGptImage15.description",
      },
      {
        image_provider_id: "azure_gpt_image_1",
        model_name: "", // Extracted from deployment in target URI
        provider_name: "azure",
        title: "Azure OpenAI GPT Image 1",
        descriptionKey: "providers.azureGptImage1.description",
      },
    ],
  },
  {
    name: "Google Cloud Vertex AI",
    providers: [
      {
        image_provider_id: "gemini-2.5-flash-image",
        model_name: "gemini-2.5-flash-image",
        provider_name: "vertex_ai",
        title: "Gemini 2.5 Flash Image",
        descriptionKey: "providers.gemini25FlashImage.description",
      },
      {
        image_provider_id: "gemini-3-pro-image",
        model_name: "gemini-3-pro-image",
        provider_name: "vertex_ai",
        title: "Gemini 3 Pro Image",
        descriptionKey: "providers.gemini3ProImage.description",
      },
      {
        image_provider_id: "gemini-3-pro-image-preview",
        model_name: "gemini-3-pro-image-preview",
        provider_name: "vertex_ai",
        title: "Gemini 3 Pro Image Preview",
        descriptionKey: "providers.gemini3ProImagePreview.description",
        deprecated: true,
      },
    ],
  },
];
