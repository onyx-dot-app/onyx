"use client";

import { useSWRConfig } from "swr";
import { LLMProviderFormProps, LLMProviderName } from "@/interfaces/llm";
import {
  useInitialValues,
  buildValidationSchema,
} from "@/sections/modals/llmConfig/utils";
import {
  submitLLMProvider,
  submitOnboardingProvider,
} from "@/sections/modals/llmConfig/svc";
import {
  APIKeyField,
  ModelSelectionField,
  DisplayNameField,
  ModelAccessField,
  ModalWrapper,
} from "@/sections/modals/llmConfig/shared";
import * as InputLayouts from "@/layouts/input-layouts";

export default function AnthropicModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  onOpenChange,
  defaultModelName,
  onboardingState,
  onboardingActions,
  llmDescriptor,
}: LLMProviderFormProps) {
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();

  const onClose = () => onOpenChange?.(false);

  const initialValues = useInitialValues(
    isOnboarding,
    LLMProviderName.ANTHROPIC,
    existingLlmProvider
  );

  const validationSchema = buildValidationSchema(isOnboarding, {
    apiKey: true,
  });

  return (
    <ModalWrapper
      providerName={LLMProviderName.ANTHROPIC}
      llmProvider={existingLlmProvider}
      onClose={onClose}
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={async (values, { setSubmitting, setStatus }) => {
        if (isOnboarding && onboardingState && onboardingActions) {
          await submitOnboardingProvider({
            providerName: LLMProviderName.ANTHROPIC,
            payload: {
              ...values,
            },
            onboardingState,
            onboardingActions,
            isCustomProvider: false,
            onClose,
            setIsSubmitting: setSubmitting,
          });
        } else {
          await submitLLMProvider({
            providerName: LLMProviderName.ANTHROPIC,
            values,
            initialValues,
            existingLlmProvider,
            shouldMarkAsDefault,
            setStatus,
            mutate,
            onClose,
            setSubmitting,
          });
        }
      }}
    >
      <APIKeyField providerName="Anthropic" />

      {!isOnboarding && (
        <>
          <InputLayouts.FieldSeparator />
          <DisplayNameField disabled={!!existingLlmProvider} />
        </>
      )}

      <InputLayouts.FieldSeparator />
      <ModelSelectionField shouldShowAutoUpdateToggle={true} />

      {!isOnboarding && (
        <>
          <InputLayouts.FieldSeparator />
          <ModelAccessField />
        </>
      )}
    </ModalWrapper>
  );
}
