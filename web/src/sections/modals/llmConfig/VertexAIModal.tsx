"use client";

import { useState } from "react";
import { useSWRConfig } from "swr";
import { Formik } from "formik";
import { FileUploadFormField } from "@/components/Field";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import * as InputLayouts from "@/layouts/input-layouts";
import { LLMProviderFormProps } from "@/interfaces/llm";
import * as Yup from "yup";
import { useWellKnownLLMProvider } from "@/hooks/useLLMProviders";
import { LLMConfigurationModalWrapper } from "./LLMConfigurationModalWrapper";
import {
  buildDefaultInitialValues,
  buildDefaultValidationSchema,
  buildAvailableModelConfigurations,
  submitLLMProvider,
  submitOnboardingProvider,
  buildOnboardingInitialValues,
  BaseLLMFormValues,
} from "./formUtils";
import {
  DisplayModelsField,
  DisplayNameField,
  ModelsAccessField,
  SingleDefaultModelField,
} from "./shared";
import Separator from "@/refresh-components/Separator";

export const VERTEXAI_PROVIDER_NAME = "vertex_ai";
const VERTEXAI_DISPLAY_NAME = "Google Cloud Vertex AI";
const VERTEXAI_DEFAULT_MODEL = "gemini-2.5-pro";
const VERTEXAI_DEFAULT_LOCATION = "global";

interface VertexAIModalValues extends BaseLLMFormValues {
  custom_config: {
    vertex_credentials: string;
    vertex_location: string;
  };
}

export function VertexAIModal({
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
  const { wellKnownLLMProvider } = useWellKnownLLMProvider(
    VERTEXAI_PROVIDER_NAME
  );

  if (open === false) return null;

  const onClose = () => onOpenChange?.(false);

  const modelConfigurations = buildAvailableModelConfigurations(
    existingLlmProvider,
    wellKnownLLMProvider ?? llmDescriptor
  );

  const initialValues: VertexAIModalValues = isOnboarding
    ? ({
        ...buildOnboardingInitialValues(),
        name: VERTEXAI_PROVIDER_NAME,
        provider: VERTEXAI_PROVIDER_NAME,
        default_model_name: VERTEXAI_DEFAULT_MODEL,
        custom_config: {
          vertex_credentials: "",
          vertex_location: VERTEXAI_DEFAULT_LOCATION,
        },
      } as VertexAIModalValues)
    : {
        ...buildDefaultInitialValues(existingLlmProvider, modelConfigurations),
        default_model_name:
          wellKnownLLMProvider?.recommended_default_model?.name ??
          VERTEXAI_DEFAULT_MODEL,
        is_auto_mode: existingLlmProvider?.is_auto_mode ?? true,
        custom_config: {
          vertex_credentials:
            (existingLlmProvider?.custom_config
              ?.vertex_credentials as string) ?? "",
          vertex_location:
            (existingLlmProvider?.custom_config?.vertex_location as string) ??
            VERTEXAI_DEFAULT_LOCATION,
        },
      };

  const validationSchema = isOnboarding
    ? Yup.object().shape({
        default_model_name: Yup.string().required("Model name is required"),
        custom_config: Yup.object({
          vertex_credentials: Yup.string().required(
            "Credentials file is required"
          ),
          vertex_location: Yup.string(),
        }),
      })
    : buildDefaultValidationSchema().shape({
        custom_config: Yup.object({
          vertex_credentials: Yup.string().required(
            "Credentials file is required"
          ),
          vertex_location: Yup.string(),
        }),
      });

  return (
    <Formik
      initialValues={initialValues}
      validationSchema={validationSchema}
      validateOnMount={true}
      onSubmit={async (values, { setSubmitting }) => {
        const filteredCustomConfig = Object.fromEntries(
          Object.entries(values.custom_config || {}).filter(
            ([key, v]) => key === "vertex_credentials" || v !== ""
          )
        );

        const submitValues = {
          ...values,
          custom_config:
            Object.keys(filteredCustomConfig).length > 0
              ? filteredCustomConfig
              : undefined,
        };

        if (isOnboarding && onboardingState && onboardingActions) {
          const modelConfigsToUse =
            (wellKnownLLMProvider ?? llmDescriptor)?.known_models ?? [];

          await submitOnboardingProvider({
            providerName: VERTEXAI_PROVIDER_NAME,
            payload: {
              ...submitValues,
              model_configurations: modelConfigsToUse,
              is_auto_mode:
                values.default_model_name === VERTEXAI_DEFAULT_MODEL,
            },
            onboardingState,
            onboardingActions,
            isCustomProvider: false,
            onClose,
            setIsSubmitting: setSubmitting,
            setApiStatus: () => {},
            setShowApiMessage: () => {},
          });
        } else {
          await submitLLMProvider({
            providerName: VERTEXAI_PROVIDER_NAME,
            values: submitValues,
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
          providerEndpoint={VERTEXAI_PROVIDER_NAME}
          providerName={VERTEXAI_DISPLAY_NAME}
          existingProviderName={existingLlmProvider?.name}
          onClose={onClose}
          isFormValid={formikProps.isValid}
          isTesting={isTesting}
        >
          {!isOnboarding && (
            <DisplayNameField disabled={!!existingLlmProvider} />
          )}

          <FileUploadFormField
            name="custom_config.vertex_credentials"
            label="Credentials File"
            subtext="Upload your Google Cloud service account JSON credentials file."
          />

          <InputLayouts.Vertical
            name="custom_config.vertex_location"
            title="Location"
            description="The Google Cloud region for your Vertex AI models (e.g., global, us-east1, us-central1, europe-west1)."
            optional
          >
            <InputTypeInField
              name="custom_config.vertex_location"
              placeholder={VERTEXAI_DEFAULT_LOCATION}
            />
          </InputLayouts.Vertical>

          <Separator />

          {isOnboarding ? (
            <SingleDefaultModelField placeholder="E.g. gemini-2.5-pro" />
          ) : (
            <DisplayModelsField
              modelConfigurations={modelConfigurations}
              formikProps={formikProps}
              recommendedDefaultModel={
                wellKnownLLMProvider?.recommended_default_model ?? null
              }
              shouldShowAutoUpdateToggle={true}
            />
          )}

          {!isOnboarding && <ModelsAccessField formikProps={formikProps} />}
        </LLMConfigurationModalWrapper>
      )}
    </Formik>
  );
}
