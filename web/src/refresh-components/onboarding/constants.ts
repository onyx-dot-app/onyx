import { OnboardingStep } from "./types";
import SvgSearchMenu from "@/icons/search-menu";
import SvgGlobe from "@/icons/globe";
import SvgImage from "@/icons/image";
import SvgUsers from "@/icons/users";
import SvgStep2 from "@/icons/step2";
import SvgStep3 from "@/icons/step3";
import { FinalStepItemProps } from "./types";
import { SvgProps } from "@/icons";
import { AzureIcon, GeminiIcon } from "@/components/icons/icons";
import SvgClaude from "@/icons/claude";
import SvgAws from "@/icons/aws";
import SvgOllama from "@/icons/ollama";
import SvgOpenai from "@/icons/openai";
import SvgOpenrouter from "@/icons/openrouter";
type StepConfig = {
  index: number;
  title: string;
  buttonText: string;
  icon: React.FunctionComponent<SvgProps> | undefined;
};

export const STEP_CONFIG: Record<OnboardingStep, StepConfig> = {
  [OnboardingStep.Name]: {
    index: 1,
    title: "Let's take a moment to get you set up.",
    buttonText: "Next",
    icon: SvgStep2,
  },
  [OnboardingStep.LlmSetup]: {
    index: 2,
    title: "Almost there! Connect your models to start chatting.",
    buttonText: "Finish Setup",
    icon: SvgStep3,
  },
  [OnboardingStep.Complete]: {
    index: 3,
    title:
      "You're all set! It might be helpful to review the following settings.",
    buttonText: "",
    icon: undefined,
  },
} as const;

export const TOTAL_STEPS = 3;

export const STEP_NAVIGATION: Record<
  OnboardingStep,
  { next?: OnboardingStep; prev?: OnboardingStep }
> = {
  [OnboardingStep.Name]: { next: OnboardingStep.LlmSetup },
  [OnboardingStep.LlmSetup]: {
    next: OnboardingStep.Complete,
    prev: OnboardingStep.Name,
  },
  [OnboardingStep.Complete]: { prev: OnboardingStep.LlmSetup },
};

export const FINAL_SETUP_CONFIG: FinalStepItemProps[] = [
  {
    title: "Set up document search with RAG (Retrieval Augmented Generation)",
    description:
      "Select embedding models used to search across large bodies of documents.",
    icon: SvgSearchMenu,
    buttonText: "Search Settings",
  },
  {
    title: "Select web search provider",
    description: "Set up web search and search across the internet.",
    icon: SvgGlobe,
    buttonText: "Web Search",
  },
  {
    title: "Enable image generation",
    description:
      "Set up image generation models to create images in your chat.",
    icon: SvgImage,
    buttonText: "Image Generation",
  },
  {
    title: "Invite your team",
    description: "Add and manage users and groups in your team.",
    icon: SvgUsers,
    buttonText: "Manage Users",
  },
];

export const PROVIDER_ICON_MAP: Record<
  string,
  React.FunctionComponent<SvgProps>
> = {
  anthropic: SvgClaude,
  bedrock: SvgAws,
  azure: AzureIcon,
  vertex_ai: GeminiIcon,
  openai: SvgOpenai,
  ollama: SvgOllama,
  openrouter: SvgOpenrouter,
};

export const MODAL_CONTENT_MAP: Record<string, any> = {
  openai: {
    description: "Connect to OpenAI and set up your chatGPT models.",
    display_name: "OpenAI",
    field_metadata: {
      api_key: "https://platform.openai.com/api-keys",
      default_model_name:
        "This model will be used by Onyx by default for chatGPT.",
    },
  },
  anthropic: {
    description: "Connect to Anthropic and set up your Claude models.",
    display_name: "Anthropic",
    field_metadata: {
      default_model_name:
        "This model will be used by Onyx by default for Claude.",
    },
  },
  ollama: {
    description: "Connect to your Ollama models.",
    display_name: "Ollama",
    field_metadata: {
      api_base:
        "Your Ollama server URL (e.g., http://127.0.0.1:11434 for local)",
      api_key: "https://ollama.com",
      default_model_name:
        "This model will be used by Onyx by default for Ollama.",
    },
  },
  azure: {
    description:
      "Connect to Microsoft Azure and set up your Azure OpenAI models.",
    display_name: "Azure OpenAI",
    field_metadata: {
      api_key: "https://oai.azure.com",
      default_model_name:
        "This model will be used by Onyx by default for Azure OpenAI.",
    },
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
  ollama: {
    tabs: [
      {
        id: "self-hosted",
        label: "Self-hosted Ollama",
        fields: ["api_base", "default_model_name"],
        fieldOverrides: {
          api_base: {
            placeholder: "http://127.0.0.1:11434",
            description: "Your self-hosted Ollama API URL.",
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
            description:
              "Paste your API key from Ollama Cloud to access your models.",
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
  vertex_ai: ["vertex_location"],
};

export const HIDE_API_MESSAGE_FIELDS: Record<string, string[]> = {
  bedrock: ["BEDROCK_AUTH_METHOD", "AWS_REGION_NAME"],
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
