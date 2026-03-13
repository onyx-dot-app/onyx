import React from "react";
import {
  WellKnownLLMProviderDescriptor,
  LLMProviderName,
} from "@/interfaces/llm";
import { OnboardingActions, OnboardingState } from "@/interfaces/onboarding";
import OpenAIModal from "@/sections/modals/llmConfig/OpenAIModal";
import AnthropicModal from "@/sections/modals/llmConfig/AnthropicModal";
import OllamaModal from "@/sections/modals/llmConfig/OllamaModal";
import AzureModal from "@/sections/modals/llmConfig/AzureModal";
import BedrockModal from "@/sections/modals/llmConfig/BedrockModal";
import VertexAIModal from "@/sections/modals/llmConfig/VertexAIModal";
import OpenRouterModal from "@/sections/modals/llmConfig/OpenRouterModal";
import CustomModal from "@/sections/modals/llmConfig/CustomModal";
import LMStudioForm from "@/sections/modals/llmConfig/LMStudioForm";
import LiteLLMProxyModal from "@/sections/modals/llmConfig/LiteLLMProxyModal";

// Display info for LLM provider cards - title is the product name, displayName is the company/platform
const PROVIDER_DISPLAY_INFO: Record<
  string,
  { title: string; displayName: string }
> = {
  [LLMProviderName.OPENAI]: { title: "GPT", displayName: "OpenAI" },
  [LLMProviderName.ANTHROPIC]: { title: "Claude", displayName: "Anthropic" },
  [LLMProviderName.OLLAMA_CHAT]: { title: "Ollama", displayName: "Ollama" },
  [LLMProviderName.AZURE]: {
    title: "Azure OpenAI",
    displayName: "Microsoft Azure Cloud",
  },
  [LLMProviderName.BEDROCK]: {
    title: "Amazon Bedrock",
    displayName: "AWS",
  },
  [LLMProviderName.VERTEX_AI]: {
    title: "Gemini",
    displayName: "Google Cloud Vertex AI",
  },
  [LLMProviderName.OPENROUTER]: {
    title: "OpenRouter",
    displayName: "OpenRouter",
  },
  [LLMProviderName.LM_STUDIO]: {
    title: "LM Studio",
    displayName: "LM Studio",
  },
  [LLMProviderName.LITELLM_PROXY]: {
    title: "LiteLLM Proxy",
    displayName: "LiteLLM Proxy",
  },
};

export function getProviderDisplayInfo(providerName: string): {
  title: string;
  displayName: string;
} {
  return (
    PROVIDER_DISPLAY_INFO[providerName] ?? {
      title: providerName,
      displayName: providerName,
    }
  );
}

export interface OnboardingFormProps {
  llmDescriptor?: WellKnownLLMProviderDescriptor;
  isCustomProvider?: boolean;
  onboardingState: OnboardingState;
  onboardingActions: OnboardingActions;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function getOnboardingForm({
  llmDescriptor,
  isCustomProvider,
  onboardingState,
  onboardingActions,
  open,
  onOpenChange,
}: OnboardingFormProps): React.ReactNode {
  const sharedProps = {
    variant: "onboarding" as const,
    onboardingState,
    onboardingActions,
    open,
    onOpenChange,
  };

  // Handle custom provider
  if (isCustomProvider || !llmDescriptor) {
    return <CustomModal {...sharedProps} />;
  }

  const providerProps = {
    ...sharedProps,
    llmDescriptor,
  };

  switch (llmDescriptor.name) {
    case LLMProviderName.OPENAI:
      return <OpenAIModal {...providerProps} />;

    case LLMProviderName.ANTHROPIC:
      return <AnthropicModal {...providerProps} />;

    case LLMProviderName.OLLAMA_CHAT:
      return <OllamaModal {...providerProps} />;

    case LLMProviderName.AZURE:
      return <AzureModal {...providerProps} />;

    case LLMProviderName.BEDROCK:
      return <BedrockModal {...providerProps} />;

    case LLMProviderName.VERTEX_AI:
      return <VertexAIModal {...providerProps} />;

    case LLMProviderName.OPENROUTER:
      return <OpenRouterModal {...providerProps} />;

    case LLMProviderName.LM_STUDIO:
      return <LMStudioForm {...providerProps} />;

    case LLMProviderName.LITELLM_PROXY:
      return <LiteLLMProxyModal {...providerProps} />;

    default:
      return <CustomModal {...sharedProps} />;
  }
}
