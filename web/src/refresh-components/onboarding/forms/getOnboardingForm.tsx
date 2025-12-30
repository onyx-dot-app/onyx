import React from "react";
import {
  WellKnownLLMProviderDescriptor,
  LLMProviderName,
} from "@/app/admin/configuration/llm/interfaces";
import { OnboardingActions, OnboardingState } from "../types";
import { OpenAIOnboardingForm } from "./OpenAIOnboardingForm";
import { AnthropicOnboardingForm } from "./AnthropicOnboardingForm";
import { OllamaOnboardingForm } from "./OllamaOnboardingForm";
import { AzureOnboardingForm } from "./AzureOnboardingForm";
import { BedrockOnboardingForm } from "./BedrockOnboardingForm";
import { VertexAIOnboardingForm } from "./VertexAIOnboardingForm";
import { OpenRouterOnboardingForm } from "./OpenRouterOnboardingForm";
import { CustomOnboardingForm } from "./CustomOnboardingForm";

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
  // Handle custom provider
  if (isCustomProvider || !llmDescriptor) {
    return (
      <CustomOnboardingForm
        onboardingState={onboardingState}
        onboardingActions={onboardingActions}
        open={open}
        onOpenChange={onOpenChange}
      />
    );
  }

  // Map provider name to form component
  switch (llmDescriptor.name) {
    case LLMProviderName.OPENAI:
      return (
        <OpenAIOnboardingForm
          llmDescriptor={llmDescriptor}
          onboardingState={onboardingState}
          onboardingActions={onboardingActions}
          open={open}
          onOpenChange={onOpenChange}
        />
      );

    case LLMProviderName.ANTHROPIC:
      return (
        <AnthropicOnboardingForm
          llmDescriptor={llmDescriptor}
          onboardingState={onboardingState}
          onboardingActions={onboardingActions}
          open={open}
          onOpenChange={onOpenChange}
        />
      );

    case LLMProviderName.OLLAMA_CHAT:
      return (
        <OllamaOnboardingForm
          llmDescriptor={llmDescriptor}
          onboardingState={onboardingState}
          onboardingActions={onboardingActions}
          open={open}
          onOpenChange={onOpenChange}
        />
      );

    case LLMProviderName.AZURE:
      return (
        <AzureOnboardingForm
          llmDescriptor={llmDescriptor}
          onboardingState={onboardingState}
          onboardingActions={onboardingActions}
          open={open}
          onOpenChange={onOpenChange}
        />
      );

    case LLMProviderName.BEDROCK:
      return (
        <BedrockOnboardingForm
          llmDescriptor={llmDescriptor}
          onboardingState={onboardingState}
          onboardingActions={onboardingActions}
          open={open}
          onOpenChange={onOpenChange}
        />
      );

    case LLMProviderName.VERTEX_AI:
      return (
        <VertexAIOnboardingForm
          llmDescriptor={llmDescriptor}
          onboardingState={onboardingState}
          onboardingActions={onboardingActions}
          open={open}
          onOpenChange={onOpenChange}
        />
      );

    case LLMProviderName.OPENROUTER:
      return (
        <OpenRouterOnboardingForm
          llmDescriptor={llmDescriptor}
          onboardingState={onboardingState}
          onboardingActions={onboardingActions}
          open={open}
          onOpenChange={onOpenChange}
        />
      );

    default:
      // Fallback to custom form for unknown providers
      return (
        <CustomOnboardingForm
          onboardingState={onboardingState}
          onboardingActions={onboardingActions}
          open={open}
          onOpenChange={onOpenChange}
        />
      );
  }
}
