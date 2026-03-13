"use client";

import { useState } from "react";
import { useSWRConfig } from "swr";
import { Formik } from "formik";
import { LLMProviderFormProps } from "@/interfaces/llm";
import * as Yup from "yup";
import { useWellKnownLLMProvider } from "@/hooks/useLLMProviders";
import {
  buildDefaultInitialValues,
  buildDefaultValidationSchema,
  buildAvailableModelConfigurations,
  submitLLMProvider,
  submitOnboardingProvider,
  buildOnboardingInitialValues,
} from "@/sections/modals/llmConfig/formUtils";
import {
  APIKeyField,
  ModelsField,
  DisplayNameField,
  FieldSeparator,
  ModelsAccessField,
  SingleDefaultModelField,
  LLMConfigurationModalWrapper,
} from "@/sections/modals/llmConfig/shared";

const OPENAI_PROVIDER_NAME = "openai";
const DEFAULT_DEFAULT_MODEL_NAME = "gpt-5.2";

export default function OpenAIModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  open,
  onOpenChange,
  onboardingState,
  onboardingActions,
  llmDescriptor,
}: LLMProviderFormProps) {
  const isOnboarding = variant === "onboarding";
  const [isTesting, setIsTesting] = useState(false);
  const { mutate } = useSWRConfig();
  const { wellKnownLLMProvider } =
    useWellKnownLLMProvider(OPENAI_PROVIDER_NAME);

  if (open === false) return null;

  const onClose = () => onOpenChange?.(false);

  const modelConfigurations = buildAvailableModelConfigurations(
    existingLlmProvider,
    wellKnownLLMProvider ?? llmDescriptor
  );

  const initialValues = isOnboarding
    ? {
        ...buildOnboardingInitialValues(),
        name: OPENAI_PROVIDER_NAME,
        provider: OPENAI_PROVIDER_NAME,
        api_key: "",
        default_model_name: DEFAULT_DEFAULT_MODEL_NAME,
      }
    : {
        ...buildDefaultInitialValues(existingLlmProvider, modelConfigurations),
        api_key: existingLlmProvider?.api_key ?? "",
        default_model_name:
          wellKnownLLMProvider?.recommended_default_model?.name ??
          DEFAULT_DEFAULT_MODEL_NAME,
        is_auto_mode: existingLlmProvider?.is_auto_mode ?? true,
      };

  const validationSchema = isOnboarding
    ? Yup.object().shape({
        api_key: Yup.string().required("API Key is required"),
        default_model_name: Yup.string().required("Model name is required"),
      })
    : buildDefaultValidationSchema().shape({
        api_key: Yup.string().required("API Key is required"),
      });

  return (
    <Formik
      initialValues={initialValues}
      validationSchema={validationSchema}
      validateOnMount={true}
      onSubmit={async (values, { setSubmitting }) => {
        if (isOnboarding && onboardingState && onboardingActions) {
          const modelConfigsToUse =
            (wellKnownLLMProvider ?? llmDescriptor)?.known_models ?? [];

          await submitOnboardingProvider({
            providerName: OPENAI_PROVIDER_NAME,
            payload: {
              ...values,
              model_configurations: modelConfigsToUse,
              is_auto_mode:
                values.default_model_name === DEFAULT_DEFAULT_MODEL_NAME,
            },
            onboardingState,
            onboardingActions,
            isCustomProvider: false,
            onClose,
            setIsSubmitting: setSubmitting,
          });
        } else {
          await submitLLMProvider({
            providerName: OPENAI_PROVIDER_NAME,
            values,
            initialValues,
            modelConfigurations,
            existingLlmProvider,
            shouldMarkAsDefault,
            setIsTesting,
            mutate,
            onClose,
            setSubmitting,
          });
        }
      }}
    >
      {(formikProps) => (
        <LLMConfigurationModalWrapper
          providerEndpoint={OPENAI_PROVIDER_NAME}
          existingProviderName={existingLlmProvider?.name}
          onClose={onClose}
          isFormValid={formikProps.isValid}
          isDirty={formikProps.dirty}
          isTesting={isTesting}
          isSubmitting={formikProps.isSubmitting}
        >
          <APIKeyField providerName="OpenAI" />

          {!isOnboarding && (
            <>
              <FieldSeparator />
              <DisplayNameField disabled={!!existingLlmProvider} />
            </>
          )}

          <FieldSeparator />
          {isOnboarding ? (
            <SingleDefaultModelField placeholder="E.g. gpt-5.2" />
          ) : (
            <ModelsField
              modelConfigurations={modelConfigurations}
              formikProps={formikProps}
              recommendedDefaultModel={
                wellKnownLLMProvider?.recommended_default_model ?? null
              }
              shouldShowAutoUpdateToggle={true}
            />
          )}

          {!isOnboarding && (
            <>
              <FieldSeparator />
              <ModelsAccessField formikProps={formikProps} />
            </>
          )}
        </LLMConfigurationModalWrapper>
      )}
    </Formik>
  );
}
