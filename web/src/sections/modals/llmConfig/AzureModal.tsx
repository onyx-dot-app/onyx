"use client";

import { useState } from "react";
import { useSWRConfig } from "swr";
import { Formik } from "formik";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import * as InputLayouts from "@/layouts/input-layouts";
import { LLMProviderFormProps, LLMProviderView } from "@/interfaces/llm";
import * as Yup from "yup";
import { useWellKnownLLMProvider } from "@/hooks/useLLMProviders";
import { LLMConfigurationModalWrapper } from "@/sections/modals/llmConfig/LLMConfigurationModalWrapper";
import {
  buildDefaultInitialValues,
  buildDefaultValidationSchema,
  buildAvailableModelConfigurations,
  submitLLMProvider,
  submitOnboardingProvider,
  buildOnboardingInitialValues,
  BaseLLMFormValues,
} from "@/sections/modals/llmConfig/formUtils";
import {
  APIKeyField,
  DisplayNameField,
  FieldSeparator,
  FieldWrapper,
  ModelsAccessField,
  ModelsField,
  SingleDefaultModelField,
} from "@/sections/modals/llmConfig/shared";
import {
  isValidAzureTargetUri,
  parseAzureTargetUri,
} from "@/lib/azureTargetUri";

export const AZURE_PROVIDER_NAME = "azure";

interface AzureModalValues extends BaseLLMFormValues {
  api_key: string;
  target_uri: string;
  api_base?: string;
  api_version?: string;
  deployment_name?: string;
}

function buildTargetUri(existingLlmProvider?: LLMProviderView): string {
  if (!existingLlmProvider?.api_base || !existingLlmProvider?.api_version) {
    return "";
  }

  const deploymentName =
    existingLlmProvider.deployment_name || "your-deployment";
  return `${existingLlmProvider.api_base}/openai/deployments/${deploymentName}/chat/completions?api-version=${existingLlmProvider.api_version}`;
}

const processValues = (values: AzureModalValues): AzureModalValues => {
  let processedValues = { ...values };
  if (values.target_uri) {
    try {
      const { url, apiVersion, deploymentName } = parseAzureTargetUri(
        values.target_uri
      );
      processedValues = {
        ...processedValues,
        api_base: url.origin,
        api_version: apiVersion,
        deployment_name: deploymentName || processedValues.deployment_name,
      };
    } catch (error) {
      console.error("Failed to parse target_uri:", error);
    }
  }
  return processedValues;
};

export function AzureModal({
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
  const { wellKnownLLMProvider } = useWellKnownLLMProvider(AZURE_PROVIDER_NAME);

  if (open === false) return null;

  const onClose = () => onOpenChange?.(false);

  const modelConfigurations = buildAvailableModelConfigurations(
    existingLlmProvider,
    wellKnownLLMProvider ?? llmDescriptor
  );

  const initialValues: AzureModalValues = isOnboarding
    ? ({
        ...buildOnboardingInitialValues(),
        name: AZURE_PROVIDER_NAME,
        provider: AZURE_PROVIDER_NAME,
        api_key: "",
        target_uri: "",
        default_model_name: "",
      } as AzureModalValues)
    : {
        ...buildDefaultInitialValues(existingLlmProvider, modelConfigurations),
        api_key: existingLlmProvider?.api_key ?? "",
        target_uri: buildTargetUri(existingLlmProvider),
      };

  const validationSchema = isOnboarding
    ? Yup.object().shape({
        api_key: Yup.string().required("API Key is required"),
        target_uri: Yup.string()
          .required("Target URI is required")
          .test(
            "valid-target-uri",
            "Target URI must be a valid URL with api-version query parameter and either a deployment name in the path or /openai/responses",
            (value) => (value ? isValidAzureTargetUri(value) : false)
          ),
        default_model_name: Yup.string().required("Model name is required"),
      })
    : buildDefaultValidationSchema().shape({
        api_key: Yup.string().required("API Key is required"),
        target_uri: Yup.string()
          .required("Target URI is required")
          .test(
            "valid-target-uri",
            "Target URI must be a valid URL with api-version query parameter and either a deployment name in the path or /openai/responses",
            (value) => (value ? isValidAzureTargetUri(value) : false)
          ),
      });

  return (
    <Formik
      initialValues={initialValues}
      validationSchema={validationSchema}
      validateOnMount={true}
      onSubmit={async (values, { setSubmitting }) => {
        const processedValues = processValues(values);

        if (isOnboarding && onboardingState && onboardingActions) {
          const modelConfigsToUse =
            (wellKnownLLMProvider ?? llmDescriptor)?.known_models ?? [];

          await submitOnboardingProvider({
            providerName: AZURE_PROVIDER_NAME,
            payload: {
              ...processedValues,
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
            providerName: AZURE_PROVIDER_NAME,
            values: processedValues,
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
          providerEndpoint={AZURE_PROVIDER_NAME}
          existingProviderName={existingLlmProvider?.name}
          onClose={onClose}
          isFormValid={formikProps.isValid}
          isTesting={isTesting}
        >
          <FieldWrapper>
            <InputLayouts.Vertical
              name="target_uri"
              title="Target URI"
              subDescription="Paste your endpoint target URI from Azure OpenAI (including API endpoint base, deployment name, and API version)."
            >
              <InputTypeInField
                name="target_uri"
                placeholder="https://your-resource.cognitiveservices.azure.com/openai/deployments/deployment-name/chat/completions?api-version=2025-01-01-preview"
              />
            </InputLayouts.Vertical>
          </FieldWrapper>

          <APIKeyField providerName="Azure" />

          {!isOnboarding && (
            <>
              <FieldSeparator />
              <DisplayNameField disabled={!!existingLlmProvider} />
            </>
          )}

          <FieldSeparator />

          {isOnboarding ? (
            <SingleDefaultModelField placeholder="E.g. gpt-4o" />
          ) : (
            <ModelsField
              modelConfigurations={modelConfigurations}
              formikProps={formikProps}
              recommendedDefaultModel={null}
              shouldShowAutoUpdateToggle={false}
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
