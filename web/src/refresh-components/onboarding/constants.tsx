import { OnboardingStep } from "./types";
import type { ReactNode } from "react";
import SvgGlobe from "@/icons/globe";
import SvgImage from "@/icons/image";
import SvgUsers from "@/icons/users";
import { FinalStepItemProps } from "./types";
import { SvgProps } from "@/icons";
import { AzureIcon, GeminiIcon } from "@/components/icons/icons";
import SvgClaude from "@/icons/claude";
import SvgAws from "@/icons/aws";
import SvgOllama from "@/icons/ollama";
import SvgOpenai from "@/icons/openai";
import SvgOpenrouter from "@/icons/openrouter";
import { LLMProviderName } from "@/app/admin/configuration/llm/interfaces";
import InlineExternalLink from "../InlineExternalLink";

type StepConfig = {
  index: number;
  title: string;
  buttonText: string;
  iconPercentage: number;
};

export const STEP_CONFIG: Record<OnboardingStep, StepConfig> = {
  [OnboardingStep.Welcome]: {
    index: 0,
    title: "Commençons par configurer votre application.",
    buttonText: "Commencer",
    iconPercentage: 10,
  },
  [OnboardingStep.Name]: {
    index: 1,
    title: "Prenons un moment pour configurer votre environnement.",
    buttonText: "Suivant",
    iconPercentage: 40,
  },
  [OnboardingStep.LlmSetup]: {
    index: 2,
    title: "Presque terminé ! Connectez vos modèles pour commencer à discuter.",
    buttonText: "Suivant",
    iconPercentage: 70,
  },
  [OnboardingStep.Complete]: {
    index: 3,
    title: "Tout est prêt ! Consultez les paramètres optionnels ou cliquez sur Terminer la configuration.",
    buttonText: "Terminer la configuration",
    iconPercentage: 100,
  },
} as const;

export const TOTAL_STEPS = 3;

export const STEP_NAVIGATION: Record<
  OnboardingStep,
  { next?: OnboardingStep; prev?: OnboardingStep }
> = {
  [OnboardingStep.Welcome]: { next: OnboardingStep.Name },
  [OnboardingStep.Name]: {
    next: OnboardingStep.LlmSetup,
    prev: OnboardingStep.Welcome,
  },
  [OnboardingStep.LlmSetup]: {
    next: OnboardingStep.Complete,
    prev: OnboardingStep.Name,
  },
  [OnboardingStep.Complete]: { prev: OnboardingStep.LlmSetup },
};

export const FINAL_SETUP_CONFIG: FinalStepItemProps[] = [
  {
    title: "Select web search provider",
    description: "Enable Dom Engin. to search the internet for information.",
    icon: SvgGlobe,
    buttonText: "Web Search",
    buttonHref: "/admin/configuration/web-search",
  },
  {
    title: "Enable image generation",
    description: "Set up models to create images in your chats.",
    icon: SvgImage,
    buttonText: "Image Generation",
    buttonHref: "https://docs.onyx.app/overview/core_features/image_generation",
  },
  {
    title: "Invite your team",
    description: "Manage users and permissions for your team",
    icon: SvgUsers,
    buttonText: "Manage Users",
    buttonHref: "/admin/users",
  },
];

export const PROVIDER_ICON_MAP: Record<
  string,
  React.FunctionComponent<SvgProps>
> = {
  [LLMProviderName.ANTHROPIC]: SvgClaude,
  [LLMProviderName.BEDROCK]: SvgAws,
  [LLMProviderName.AZURE]: AzureIcon,
  [LLMProviderName.VERTEX_AI]: GeminiIcon,
  [LLMProviderName.OPENAI]: SvgOpenai,
  [LLMProviderName.OLLAMA_CHAT]: SvgOllama,
  [LLMProviderName.OPENROUTER]: SvgOpenrouter,
};

export const MODAL_CONTENT_MAP: Record<string, any> = {
  [LLMProviderName.OPENAI]: {
    description: "Connect to OpenAI and set up your chatGPT models.",
    display_name: "OpenAI",
    field_metadata: {
      api_key: (
        <>
          {"Paste your "}
          <InlineExternalLink href="https://platform.openai.com/api-keys">
            API key
          </InlineExternalLink>
          {" from OpenAI to access your models."}
        </>
      ),
      default_model_name:
        "This model will be used by Dom Engin. by default for chatGPT.",
    },
  },
  [LLMProviderName.ANTHROPIC]: {
    description: "Connect to Anthropic and set up your Claude models.",
    display_name: "Anthropic",
    field_metadata: {
      api_key: (
        <>
          {"Paste your "}
          <InlineExternalLink href="https://console.anthropic.com/dashboard">
            API key
          </InlineExternalLink>
          {" from Anthropic to access your models."}
        </>
      ),
      default_model_name:
        "This model will be used by Dom Engin. by default for Claude.",
    },
  },
  [LLMProviderName.OLLAMA_CHAT]: {
    description: "Connect to your Ollama models.",
    display_name: "Ollama",
    field_metadata: {
      api_base: "Your self-hosted Ollama API base URL.",
      OLLAMA_API_KEY: (
        <>
          {"Paste your "}
          <InlineExternalLink href="https://ollama.com">
            API key
          </InlineExternalLink>
          {" from Ollama Cloud to access your models."}
        </>
      ),
      default_model_name:
        "This model will be used by Dom Engin. by default for Ollama.",
    },
  },
  [LLMProviderName.VERTEX_AI]: {
    description:
      "Connect to Google Cloud Vertex AI and set up your Gemini models.",
    display_name: "Gemini",
    field_metadata: {
      vertex_credentials: (
        <>
          {"Paste your "}
          <InlineExternalLink href="https://console.cloud.google.com/projectselector2/iam-admin/serviceaccounts?supportedpurview=project">
            API key
          </InlineExternalLink>
          {" from Google Cloud Vertex AI to access your models."}
        </>
      ),
      default_model_name:
        "This model will be used by Dom Engin. by default for Gemini.",
    },
  },
  [LLMProviderName.AZURE]: {
    description:
      "Connect to Microsoft Azure and set up your Azure OpenAI models.",
    display_name: "Azure OpenAI",
    field_metadata: {
      api_key: (
        <>
          {"Paste your "}
          <InlineExternalLink href="https://oai.azure.com">
            API key
          </InlineExternalLink>
          {" from Azure OpenAI to access your models."}
        </>
      ),
      default_model_name:
        "This model will be used by Dom Engin. by default for Azure OpenAI.",
    },
  },
  [LLMProviderName.OPENROUTER]: {
    description: "Connect to OpenRouter and set up your OpenRouter models.",
    display_name: "OpenRouter",
    field_metadata: {
      api_key: (
        <>
          {"Paste your "}
          <InlineExternalLink href="https://openrouter.ai/settings/keys">
            API key
          </InlineExternalLink>
          {" from OpenRouter to access your models."}
        </>
      ),
      default_model_name:
        "This model will be used by Dom Engin. by default for OpenRouter.",
    },
  },
  [LLMProviderName.BEDROCK]: {
    description: "Connect to AWS and set up your Amazon Bedrock models.",
    display_name: "Amazon Bedrock",
    field_metadata: {
      BEDROCK_AUTH_METHOD: (
        <>
          {"See "}
          <InlineExternalLink href="https://docs.onyx.app/admin/ai_models/bedrock#authentication-methods">
            documentation
          </InlineExternalLink>
          {" for more instructions."}
        </>
      ),
      AWS_ACCESS_KEY_ID: "",
      AWS_SECRET_ACCESS_KEY: "",
      AWS_BEARER_TOKEN_BEDROCK: "",
    },
  },
  custom: {
    description:
      "Connect models from other providers or your self-hosted models.",
    display_name: "Custom Provider",
    field_metadata: {},
  },
};

// Tab configuration for providers that need multiple setup modes
export interface TabFieldConfig {
  id: string;
  label: string;
  fields: string[]; // Field names to show in this tab
  fieldOverrides?: Record<
    string,
    {
      placeholder?: string;
      description?: string;
    }
  >;
  hiddenFields?: Record<string, any>; // Fields to set but not show
}

export interface ProviderTabConfig {
  tabs: TabFieldConfig[];
}

export const PROVIDER_TAB_CONFIG: Record<string, ProviderTabConfig> = {
  [LLMProviderName.OLLAMA_CHAT]: {
    tabs: [
      {
        id: "self-hosted",
        label: "Self-hosted Ollama",
        fields: ["api_base", "default_model_name"],
        fieldOverrides: {
          api_base: {
            placeholder: "http://127.0.0.1:11434",
          },
        },
      },
      {
        id: "cloud",
        label: "Ollama Cloud",
        fields: ["custom_config.OLLAMA_API_KEY", "default_model_name"],
        fieldOverrides: {
          "custom_config.OLLAMA_API_KEY": {
            placeholder: "",
          },
        },
        hiddenFields: {
          api_base: "https://ollama.com",
        },
      },
    ],
  },
};

export const PROVIDER_SKIP_FIELDS: Record<string, string[]> = {
  [LLMProviderName.VERTEX_AI]: ["vertex_location"],
};

export const HIDE_API_MESSAGE_FIELDS: Record<string, string[]> = {
  [LLMProviderName.BEDROCK]: ["BEDROCK_AUTH_METHOD", "AWS_REGION_NAME"],
};

// Map Bedrock auth selection to which `custom_config` keys to show
export const BEDROCK_AUTH_FIELDS: Record<
  "iam" | "access_key" | "long_term_api_key",
  string[]
> = {
  iam: ["BEDROCK_AUTH_METHOD", "AWS_REGION_NAME"],
  access_key: [
    "BEDROCK_AUTH_METHOD",
    "AWS_REGION_NAME",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
  ],
  long_term_api_key: [
    "BEDROCK_AUTH_METHOD",
    "AWS_REGION_NAME",
    "AWS_BEARER_TOKEN_BEDROCK",
  ],
};
