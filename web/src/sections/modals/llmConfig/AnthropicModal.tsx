"use client";

import { useSWRConfig } from "swr";
import { Formik } from "formik";
import { LLMProviderFormProps, LLMProviderName } from "@/interfaces/llm";
import {
  useTestingModelFromLLMProvider,
  useWellKnownLLMProvider,
} from "@/hooks/useLLMProviders";
import {
  buildInitialValues,
  buildValidationSchema,
  buildAvailableModelConfigurations,
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
  const { wellKnownLLMProvider } = useWellKnownLLMProvider(
    LLMProviderName.ANTHROPIC
  );

  const onClose = () => onOpenChange?.(false);

  const modelConfigurations = buildAvailableModelConfigurations(
    existingLlmProvider,
    wellKnownLLMProvider ?? llmDescriptor
  );

  const initialValues = {
    ...buildInitialValues(LLMProviderName.ANTHROPIC, existingLlmProvider),
    test_model_name: useTestingModelFromLLMProvider(
      LLMProviderName.ANTHROPIC,
      existingLlmProvider
    ),
    is_auto_mode: existingLlmProvider?.is_auto_mode ?? true,
  };

  const validationSchema = buildValidationSchema(isOnboarding, {
    apiKey: true,
  });

  return (
    <Formik
      initialValues={initialValues}
      validationSchema={validationSchema}
      validateOnMount
      onSubmit={async (values, { setSubmitting, setStatus }) => {
        if (isOnboarding && onboardingState && onboardingActions) {
          const modelConfigsToUse =
            (wellKnownLLMProvider ?? llmDescriptor)?.known_models ?? [];

          await submitOnboardingProvider({
            providerName: LLMProviderName.ANTHROPIC,
            payload: {
              ...values,
              model_configurations: modelConfigsToUse,
              is_auto_mode: values.is_auto_mode,
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
            modelConfigurations,
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
      {() => (
        <ModalWrapper
          providerName={LLMProviderName.ANTHROPIC}
          llmProvider={existingLlmProvider}
          onClose={onClose}
        >
          <APIKeyField providerName="Anthropic" />

          {!isOnboarding && (
            <>
              <InputLayouts.FieldSeparator />
              <DisplayNameField disabled={!!existingLlmProvider} />
            </>
          )}

          <InputLayouts.FieldSeparator />
          <ModelSelectionField
            modelConfigurations={modelConfigurations}
            recommendedDefaultModel={
              wellKnownLLMProvider?.recommended_default_model ?? null
            }
            shouldShowAutoUpdateToggle={true}
          />

          {!isOnboarding && (
            <>
              <InputLayouts.FieldSeparator />
              <ModelAccessField />
            </>
          )}
        </ModalWrapper>
      )}
    </Formik>
  );
}
