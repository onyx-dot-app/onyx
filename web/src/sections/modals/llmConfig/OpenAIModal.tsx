"use client";

import { useSWRConfig } from "swr";
import { Formik } from "formik";
import { LLMProviderFormProps, LLMProviderName } from "@/interfaces/llm";
import * as Yup from "yup";
import { useWellKnownLLMProvider } from "@/hooks/useLLMProviders";
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

const DEFAULT_DEFAULT_MODEL_NAME = "gpt-5.2";

export default function OpenAIModal({
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
    LLMProviderName.OPENAI
  );

  const onClose = () => onOpenChange?.(false);

  const modelConfigurations = buildAvailableModelConfigurations(
    existingLlmProvider,
    wellKnownLLMProvider ?? llmDescriptor
  );

  const initialValues = {
    ...buildInitialValues(existingLlmProvider),
    provider: existingLlmProvider?.provider ?? LLMProviderName.OPENAI,
    api_key: existingLlmProvider?.api_key ?? "",
    test_model_name:
      existingLlmProvider?.model_configurations?.find((m) => m.is_visible)
        ?.name ??
      wellKnownLLMProvider?.recommended_default_model?.name ??
      DEFAULT_DEFAULT_MODEL_NAME,
    is_auto_mode: existingLlmProvider?.is_auto_mode ?? true,
  };

  const validationSchema = isOnboarding
    ? Yup.object().shape({
        api_key: Yup.string().required("API Key is required"),
        test_model_name: Yup.string().required("Model name is required"),
      })
    : buildValidationSchema().shape({
        api_key: Yup.string().required("API Key is required"),
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
            providerName: LLMProviderName.OPENAI,
            payload: {
              ...values,
              model_configurations: modelConfigsToUse,
              is_auto_mode:
                values.test_model_name === DEFAULT_DEFAULT_MODEL_NAME,
            },
            onboardingState,
            onboardingActions,
            isCustomProvider: false,
            onClose,
            setIsSubmitting: setSubmitting,
          });
        } else {
          await submitLLMProvider({
            providerName: LLMProviderName.OPENAI,
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
          providerEndpoint={LLMProviderName.OPENAI}
          existingProviderName={existingLlmProvider?.name}
          onClose={onClose}
        >
          <APIKeyField providerName="OpenAI" />

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
