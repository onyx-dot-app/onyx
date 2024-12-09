import {
  AnthropicIcon,
  AWSIcon,
  AzureIcon,
  CPUIcon,
  OpenAIIcon,
  GeminiIcon,
  OpenSourceIcon,
} from "@/components/icons/icons";
import { FaRobot } from "react-icons/fa";

export interface CustomConfigKey {
  name: string;
  description: string | null;
  is_required: boolean;
  is_secret: boolean;
}

export interface WellKnownLLMProviderDescriptor {
  name: string;
  display_name: string;

  deployment_name_required: boolean;
  api_key_required: boolean;
  api_base_required: boolean;
  api_version_required: boolean;

  single_model_supported: boolean;
  custom_config_keys: CustomConfigKey[] | null;
  llm_names: string[];
  default_model: string | null;
  default_fast_model: string | null;
  is_public: boolean;
  groups: number[];
}

export interface LLMProvider {
  name: string;
  provider: string;
  api_key: string | null;
  api_base: string | null;
  api_version: string | null;
  custom_config: { [key: string]: string } | null;
  default_model_name: string;
  fast_default_model_name: string | null;
  is_public: boolean;
  groups: number[];
  display_model_names: string[] | null;
  deployment_name: string | null;
}

export interface FullLLMProvider extends LLMProvider {
  id: number;
  is_default_provider: boolean | null;
  model_names: string[];
  icon?: React.FC<{ size?: number; className?: string }>;
}

export interface LLMProviderDescriptor {
  name: string;
  provider: string;
  model_names: string[];
  default_model_name: string;
  fast_default_model_name: string | null;
  is_default_provider: boolean | null;
  is_public: boolean;
  groups: number[];
  display_model_names: string[] | null;
}

export const getProviderIcon = (providerName: string, modelName?: string) => {
  switch (providerName) {
    case "openai":
      // Special cases for openai based on modelName
      if (modelName?.toLowerCase().includes("gemini")) {
        return GeminiIcon;
      }
      if (modelName?.toLowerCase().includes("claude")) {
        return AnthropicIcon;
      }
      return OpenAIIcon; // Default for openai
    case "anthropic":
      return AnthropicIcon;
    case "bedrock":
      return AWSIcon;
    case "azure":
      return AzureIcon;
    default:
      return CPUIcon;
  }
};
