"use client";

import { useState } from "react";
import { useSWRConfig } from "swr";
import { Formik } from "formik";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import * as InputLayouts from "@/layouts/input-layouts";
import {
  LLMProviderFormProps,
  LLMProviderName,
  LLMProviderView,
  ModelConfiguration,
} from "@/interfaces/llm";
import * as Yup from "yup";
import { useWellKnownLLMProvider } from "@/hooks/useLLMProviders";
import {
  useInitialValues,
  buildValidationSchema,
  buildAvailableModelConfigurations,
  BaseLLMFormValues,
} from "@/sections/modals/llmConfig/utils";
import {
  submitLLMProvider,
  submitOnboardingProvider,
} from "@/sections/modals/llmConfig/svc";
import {
  APIKeyField,
  DisplayNameField,
  ModelAccessField,
  ModelSelectionField,
  ModalWrapper,
} from "@/sections/modals/llmConfig/shared";
import {
  isValidAzureTargetUri,
  parseAzureTargetUri,
} from "@/lib/azureTargetUri";
import { toast } from "@/hooks/useToast";

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
    } catch {
      toast.warning("Failed to parse target URI — using original values.");
    }
  }
  return processedValues;
};

export default function AzureModal({
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
    LLMProviderName.AZURE
  );

  const [addedModels, setAddedModels] = useState<ModelConfiguration[]>([]);

  const onClose = () => {
    setAddedModels([]);
    onOpenChange?.(false);
  };

  const baseModelConfigurations = buildAvailableModelConfigurations(
    existingLlmProvider,
    wellKnownLLMProvider ?? llmDescriptor
  );

  // Merge base models with any user-added models (dedup by name)
  const existingNames = new Set(baseModelConfigurations.map((m) => m.name));
  const modelConfigurations = [
    ...baseModelConfigurations,
    ...addedModels.filter((m) => !existingNames.has(m.name)),
  ];

  const initialValues: AzureModalValues = {
    ...useInitialValues(
      isOnboarding,
      LLMProviderName.AZURE,
      existingLlmProvider
    ),
    target_uri: buildTargetUri(existingLlmProvider),
  } as AzureModalValues;

  const validationSchema = buildValidationSchema(isOnboarding, {
    apiKey: true,
    extra: {
      target_uri: Yup.string()
        .required("Target URI is required")
        .test(
          "valid-target-uri",
          "Target URI must be a valid URL with api-version query parameter and either a deployment name in the path or /openai/responses",
          (value) => (value ? isValidAzureTargetUri(value) : false)
        ),
    },
  });

  return (
    <Formik
      initialValues={initialValues}
      validationSchema={validationSchema}
      validateOnMount
      onSubmit={async (values, { setSubmitting, setStatus }) => {
        const processedValues = processValues(values);

        if (isOnboarding && onboardingState && onboardingActions) {
          const modelConfigsToUse =
            (wellKnownLLMProvider ?? llmDescriptor)?.known_models ?? [];

          await submitOnboardingProvider({
            providerName: LLMProviderName.AZURE,
            payload: {
              ...processedValues,
              model_configurations: modelConfigsToUse,
            },
            onboardingState,
            onboardingActions,
            isCustomProvider: false,
            onClose,
            setIsSubmitting: setSubmitting,
          });
        } else {
          await submitLLMProvider({
            providerName: LLMProviderName.AZURE,
            values: processedValues,
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
      {(formikProps) => (
        <ModalWrapper
          providerName={LLMProviderName.AZURE}
          llmProvider={existingLlmProvider}
          onClose={onClose}
        >
          <InputLayouts.FieldPadder>
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
          </InputLayouts.FieldPadder>

          <APIKeyField providerName="Azure" />

          {!isOnboarding && (
            <>
              <InputLayouts.FieldSeparator />
              <DisplayNameField disabled={!!existingLlmProvider} />
            </>
          )}

          <InputLayouts.FieldSeparator />
          <ModelSelectionField
            modelConfigurations={modelConfigurations}
            recommendedDefaultModel={null}
            shouldShowAutoUpdateToggle={false}
            onAddModel={(modelName) => {
              const newModel: ModelConfiguration = {
                name: modelName,
                is_visible: true,
                max_input_tokens: null,
                supports_image_input: false,
                supports_reasoning: false,
              };
              setAddedModels((prev) => [...prev, newModel]);
              const currentSelected =
                formikProps.values.visible_model_names ?? [];
              formikProps.setFieldValue("visible_model_names", [
                ...currentSelected,
                modelName,
              ]);
              if (!formikProps.values.test_model_name) {
                formikProps.setFieldValue("test_model_name", modelName);
              }
            }}
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
