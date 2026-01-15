export interface ImageProvider {
  image_provider_id: string; // Static unique key for UI-DB mapping
  model_name: string; // Actual model name for LLM API
  provider_name: string;
  title: string;
  description: string;
}

export interface ProviderGroup {
  name: string;
  providers: ImageProvider[];
}

export const IMAGE_PROVIDER_GROUPS: ProviderGroup[] = [
  {
    name: "OpenAI",
    providers: [
      {
        image_provider_id: "openai_gpt_image_1_5",
        model_name: "gpt-image-1.5",
        provider_name: "openai",
        title: "GPT Image 1.5",
        description:
          "OpenAI's latest Image Generation model with the highest prompt fidelity.",
      },
      {
        image_provider_id: "openai_gpt_image_1",
        model_name: "gpt-image-1",
        provider_name: "openai",
        title: "GPT Image 1",
        description:
          "A capable image generation model from OpenAI with strong prompt adherence.",
      },
      {
        image_provider_id: "openai_dalle_3",
        model_name: "dall-e-3",
        provider_name: "openai",
        title: "DALL-E 3",
        description:
          "OpenAI image generation model capable of generating rich and expressive images.",
      },
    ],
  },
  {
    name: "Azure OpenAI",
    providers: [
      {
        image_provider_id: "azure_gpt_image_1_5",
        model_name: "", // Extracted from deployment in target URI
        provider_name: "azure",
        title: "Azure OpenAI GPT Image 1.5",
        description:
          "GPT Image 1.5 image generation model hosted on Microsoft Azure.",
      },
      {
        image_provider_id: "azure_gpt_image_1",
        model_name: "", // Extracted from deployment in target URI
        provider_name: "azure",
        title: "Azure OpenAI GPT Image 1",
        description:
          "GPT Image 1 image generation model hosted on Microsoft Azure.",
      },
      {
        image_provider_id: "azure_dalle_3",
        model_name: "", // Extracted from deployment in target URI
        provider_name: "azure",
        title: "Azure OpenAI DALL-E 3",
        description:
          "DALL-E 3 image generation model hosted on Microsoft Azure.",
      },
    ],
  },
];
