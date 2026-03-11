"use client";

import { useState } from "react";
import { useSWRConfig } from "swr";
import { Formik } from "formik";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import * as InputLayouts from "@/layouts/input-layouts";
import {
  LLMProviderFormProps,
  LLMProviderName,
  ModelConfiguration,
} from "@/interfaces/llm";
import { fetchLiteLLMProxyModels } from "@/app/admin/configuration/llm/utils";
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
  APIKeyField,
  ModelsField,
  DisplayNameField,
  ModelsAccessField,
  FieldSeparator,
  FetchModelsButton,
  SingleDefaultModelField,
} from "./shared";

const LITELLM_PROXY_DISPLAY_NAME = "LiteLLM Proxy";
const DEFAULT_API_BASE = "http://localhost:4000";

interface LiteLLMProxyModalValues extends BaseLLMFormValues {
  api_key: string;
  api_base: string;
}

export function LiteLLMProxyModal({
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
    LLMProviderName.LITELLM_PROXY
  );

  if (open === false) return null;

  const onClose = () => onOpenChange?.(false);

  const modelConfigurations = buildAvailableModelConfigurations(
    existingLlmProvider,
    wellKnownLLMProvider ?? llmDescriptor
  );

  const initialValues: LiteLLMProxyModalValues = isOnboarding
    ? ({
        ...buildOnboardingInitialValues(),
        name: LLMProviderName.LITELLM_PROXY,
        provider: LLMProviderName.LITELLM_PROXY,
        api_key: "",
        api_base: DEFAULT_API_BASE,
        default_model_name: "",
      } as LiteLLMProxyModalValues)
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
            providerName: LLMProviderName.LITELLM_PROXY,
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
            providerName: LLMProviderName.LITELLM_PROXY,
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
            providerEndpoint={LLMProviderName.LITELLM_PROXY}
            providerName={LITELLM_PROXY_DISPLAY_NAME}
            existingProviderName={existingLlmProvider?.name}
            onClose={onClose}
            isFormValid={formikProps.isValid}
            isTesting={isTesting}
          >
            {!isOnboarding && (
              <DisplayNameField disabled={!!existingLlmProvider} />
            )}

            <InputLayouts.Vertical
              name="api_base"
              title="API Base URL"
              description="The base URL for your LiteLLM Proxy server (e.g., http://localhost:4000)"
            >
              <InputTypeInField
                name="api_base"
                placeholder={DEFAULT_API_BASE}
              />
            </InputLayouts.Vertical>

            <APIKeyField providerName="LiteLLM Proxy" />

            <FetchModelsButton
              onFetch={() =>
                fetchLiteLLMProxyModels({
                  api_base: formikProps.values.api_base,
                  api_key: formikProps.values.api_key,
                  provider_name: existingLlmProvider?.name,
                })
              }
              isDisabled={isFetchDisabled}
              disabledHint={
                !formikProps.values.api_base
                  ? "Enter the API base URL first."
                  : !formikProps.values.api_key
                    ? "Enter your API key first."
                    : undefined
              }
              onModelsFetched={setFetchedModels}
              autoFetchOnInitialLoad={!!existingLlmProvider}
            />

            <FieldSeparator />

            {isOnboarding ? (
              <SingleDefaultModelField placeholder="E.g. gpt-4o" />
            ) : (
              <ModelsField
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

            {!isOnboarding && <ModelsAccessField formikProps={formikProps} />}
          </LLMConfigurationModalWrapper>
        );
      }}
    </Formik>
  );
}
