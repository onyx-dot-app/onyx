"use client";

import { useState } from "react";
import { useSWRConfig } from "swr";
import Separator from "@/refresh-components/Separator";
import { Formik } from "formik";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import * as InputLayouts from "@/layouts/input-layouts";
import {
  LLMProviderFormProps,
  ModelConfiguration,
  OpenRouterModelResponse,
} from "@/interfaces/llm";
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
  AdvancedOptions,
  APIKeyField,
  DisplayModels,
  DisplayNameField,
  FetchModelsButton,
  SingleDefaultModelField,
} from "./shared";

export const OPENROUTER_PROVIDER_NAME = "openrouter";
const OPENROUTER_DISPLAY_NAME = "OpenRouter";
const DEFAULT_API_BASE = "https://openrouter.ai/api/v1";
const OPENROUTER_MODELS_API_URL = "/api/admin/llm/openrouter/available-models";

interface OpenRouterModalValues extends BaseLLMFormValues {
  api_key: string;
  api_base: string;
}

async function fetchOpenRouterModels(params: {
  apiBase: string;
  apiKey: string;
  providerName?: string;
}): Promise<{ models: ModelConfiguration[]; error?: string }> {
  if (!params.apiBase || !params.apiKey) {
    return {
      models: [],
      error: "API Base and API Key are required to fetch models",
    };
  }

  try {
    const response = await fetch(OPENROUTER_MODELS_API_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        api_base: params.apiBase,
        api_key: params.apiKey,
        provider_name: params.providerName,
      }),
    });

    if (!response.ok) {
      let errorMessage = "Failed to fetch models";
      try {
        const errorData = await response.json();
        errorMessage = errorData.detail || errorMessage;
      } catch {
        // ignore JSON parsing errors
      }
      return { models: [], error: errorMessage };
    }

    const data: OpenRouterModelResponse[] = await response.json();
    const models: ModelConfiguration[] = data.map((modelData) => ({
      name: modelData.name,
      display_name: modelData.display_name,
      is_visible: true,
      max_input_tokens: modelData.max_input_tokens,
      supports_image_input: modelData.supports_image_input,
      supports_reasoning: false,
    }));

    return { models };
  } catch (error) {
    const errorMessage =
      error instanceof Error ? error.message : "Unknown error";
    return { models: [], error: errorMessage };
  }
}

export function OpenRouterModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  open,
  onOpenChange,
  onboardingState,
  onboardingActions,
  llmDescriptor,
}: LLMProviderFormProps) {
  const [fetchedModels, setFetchedModels] = useState<ModelConfiguration[]>([]);
  const [isTesting, setIsTesting] = useState(false);
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();
  const { wellKnownLLMProvider } = useWellKnownLLMProvider(
    OPENROUTER_PROVIDER_NAME
  );

  if (open === false) return null;

  const onClose = () => onOpenChange?.(false);

  const modelConfigurations = buildAvailableModelConfigurations(
    existingLlmProvider,
    wellKnownLLMProvider ?? llmDescriptor
  );

  const initialValues: OpenRouterModalValues = isOnboarding
    ? ({
        ...buildOnboardingInitialValues(),
        name: OPENROUTER_PROVIDER_NAME,
        provider: OPENROUTER_PROVIDER_NAME,
        api_key: "",
        api_base: DEFAULT_API_BASE,
        default_model_name: "",
      } as OpenRouterModalValues)
    : {
        ...buildDefaultInitialValues(existingLlmProvider, modelConfigurations),
        api_key: existingLlmProvider?.api_key ?? "",
        api_base: existingLlmProvider?.api_base ?? DEFAULT_API_BASE,
      };

  const validationSchema = isOnboarding
    ? Yup.object().shape({
        api_key: Yup.string().required("API Key is required"),
        api_base: Yup.string().required("API Base URL is required"),
        default_model_name: Yup.string().required("Model name is required"),
      })
    : buildDefaultValidationSchema().shape({
        api_key: Yup.string().required("API Key is required"),
        api_base: Yup.string().required("API Base URL is required"),
      });

  return (
    <Formik
      initialValues={initialValues}
      validationSchema={validationSchema}
      validateOnMount={true}
      onSubmit={async (values, { setSubmitting }) => {
        if (isOnboarding && onboardingState && onboardingActions) {
          const modelConfigsToUse =
            fetchedModels.length > 0 ? fetchedModels : [];

          await submitOnboardingProvider({
            providerName: OPENROUTER_PROVIDER_NAME,
            payload: {
              ...values,
              model_configurations: modelConfigsToUse,
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
            providerName: OPENROUTER_PROVIDER_NAME,
            values,
            initialValues,
            modelConfigurations:
              fetchedModels.length > 0 ? fetchedModels : modelConfigurations,
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
      {(formikProps) => {
        const currentModels =
          fetchedModels.length > 0
            ? fetchedModels
            : existingLlmProvider?.model_configurations || modelConfigurations;

        const isFetchDisabled =
          !formikProps.values.api_base || !formikProps.values.api_key;

        return (
          <LLMConfigurationModalWrapper
            providerEndpoint={OPENROUTER_PROVIDER_NAME}
            providerName={OPENROUTER_DISPLAY_NAME}
            existingProviderName={existingLlmProvider?.name}
            onClose={onClose}
            isFormValid={formikProps.isValid}
            isTesting={isTesting}
          >
            {!isOnboarding && (
              <DisplayNameField disabled={!!existingLlmProvider} />
            )}

            <APIKeyField providerName="OpenRouter" />

            <InputLayouts.Vertical
              name="api_base"
              title="API Base URL"
              description="The base URL for OpenRouter API."
            >
              <InputTypeInField
                name="api_base"
                placeholder={DEFAULT_API_BASE}
              />
            </InputLayouts.Vertical>

            <FetchModelsButton
              onFetch={() =>
                fetchOpenRouterModels({
                  apiBase: formikProps.values.api_base,
                  apiKey: formikProps.values.api_key,
                  providerName: existingLlmProvider?.name,
                })
              }
              isDisabled={isFetchDisabled}
              disabledHint={
                !formikProps.values.api_key
                  ? "Enter your API key first."
                  : !formikProps.values.api_base
                    ? "Enter the API base URL."
                    : undefined
              }
              onModelsFetched={setFetchedModels}
              autoFetchOnInitialLoad={!!existingLlmProvider}
            />

            <Separator />

            {isOnboarding ? (
              <SingleDefaultModelField placeholder="E.g. openai/gpt-4o" />
            ) : (
              <DisplayModels
                modelConfigurations={currentModels}
                formikProps={formikProps}
                noModelConfigurationsMessage={
                  "Fetch available models first, then you'll be able to select " +
                  "the models you want to make available in Onyx."
                }
                recommendedDefaultModel={null}
                shouldShowAutoUpdateToggle={false}
              />
            )}

            {!isOnboarding && <AdvancedOptions formikProps={formikProps} />}
          </LLMConfigurationModalWrapper>
        );
      }}
    </Formik>
  );
}
