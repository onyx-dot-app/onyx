import React from "react";
import {
  WellKnownLLMProviderDescriptor,
  LLMProviderName,
  LLMProviderFormProps,
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
import LMStudioModal from "@/sections/modals/llmConfig/LMStudioModal";
import LiteLLMProxyModal from "@/sections/modals/llmConfig/LiteLLMProxyModal";
import OpenAICompatibleModal from "@/sections/modals/llmConfig/OpenAICompatibleModal";

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
  [LLMProviderName.OPENAI_COMPATIBLE]: {
    title: "OpenAI Compatible",
    displayName: "OpenAI Compatible",
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
  onOpenChange: (open: boolean) => void;
}

export function getOnboardingForm({
  llmDescriptor,
  isCustomProvider,
  onboardingState,
  onboardingActions,
  onOpenChange,
}: OnboardingFormProps): React.ReactNode {
  const providerName = isCustomProvider
    ? "custom"
    : llmDescriptor?.name ?? "custom";

  const sharedProps: LLMProviderFormProps = {
    variant: "onboarding" as const,
    shouldMarkAsDefault:
      (onboardingState?.data.llmProviders ?? []).length === 0,
    onboardingActions,
    onOpenChange,
    onSuccess: () => {
      onboardingActions.updateData({
        llmProviders: [
          ...(onboardingState?.data.llmProviders ?? []),
          providerName,
        ],
      });
      onboardingActions.setButtonActive(true);
    },
  };

  // Handle custom provider
  if (isCustomProvider || !llmDescriptor) {
    return <CustomModal {...sharedProps} />;
  }

  switch (llmDescriptor.name) {
    case LLMProviderName.OPENAI:
      return <OpenAIModal {...sharedProps} />;

    case LLMProviderName.ANTHROPIC:
      return <AnthropicModal {...sharedProps} />;

    case LLMProviderName.OLLAMA_CHAT:
      return <OllamaModal {...sharedProps} />;

    case LLMProviderName.AZURE:
      return <AzureModal {...sharedProps} />;

    case LLMProviderName.BEDROCK:
      return <BedrockModal {...sharedProps} />;

    case LLMProviderName.VERTEX_AI:
      return <VertexAIModal {...sharedProps} />;

    case LLMProviderName.OPENROUTER:
      return <OpenRouterModal {...sharedProps} />;

    case LLMProviderName.LM_STUDIO:
      return <LMStudioModal {...sharedProps} />;

    case LLMProviderName.LITELLM_PROXY:
      return <LiteLLMProxyModal {...sharedProps} />;

    case LLMProviderName.OPENAI_COMPATIBLE:
      return <OpenAICompatibleModal {...sharedProps} />;

    default:
      return <CustomModal {...sharedProps} />;
  }
}
