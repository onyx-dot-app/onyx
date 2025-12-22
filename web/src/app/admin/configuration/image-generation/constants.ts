import { JSX } from "react";
import { OpenAISVG, AzureIcon, IconProps } from "@/components/icons/icons";

export interface ImageProvider {
  id: string;
  provider_name: string;
  icon: ({ size, className }: IconProps) => JSX.Element;
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
        id: "gpt-image-1",
        provider_name: "openai",
        icon: OpenAISVG,
        title: "GPT Image 1",
        description:
          "OpenAI's latest Image Generation model with the highest prompt fidelity.",
      },
      {
        id: "dall-e-3",
        provider_name: "openai",
        icon: OpenAISVG,
        title: "DALL·E 3",
        description:
          "OpenAI image generation model capable of generating rich and expressive images.",
      },
    ],
  },
  {
    name: "Azure OpenAI",
    providers: [
      {
        id: "azure-dall-e-3", //actual model name will be extracted from the target uri
        provider_name: "azure",
        icon: AzureIcon,
        title: "Azure OpenAI DALL·E 3",
        description:
          "DALL·E 3 image generation model hosted on Microsoft Azure.",
      },
    ],
  },
];
