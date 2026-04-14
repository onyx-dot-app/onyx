"use client";

import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import { InputDivider, InputPadder, InputVertical } from "@opal/layouts";
import {
  LLMProviderFormProps,
  LLMProviderName,
  LLMProviderView,
} from "@/interfaces/llm";
import * as Yup from "yup";
import {
  useInitialValues,
  buildValidationSchema,
  BaseLLMFormValues,
} from "@/sections/modals/llmConfig/utils";
import { submitProvider } from "@/sections/modals/llmConfig/svc";
import { LLMProviderConfiguredSource } from "@/lib/analytics";
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
import { refreshLlmProviderCaches } from "@/lib/llmConfig/cache";

interface AzureModalValues extends BaseLLMFormValues {
  api_key: string;
  target_uri: string;
  api_base?: string;
  api_version?: string;
  deployment_name?: string;
}

function AzureModelSelection() {
  const formikProps = useFormikContext<AzureModalValues>();
  return (
    <ModelSelectionField
      shouldShowAutoUpdateToggle={false}
      onAddModel={(modelName) => {
        const current = formikProps.values.model_configurations;
        if (current.some((m) => m.name === modelName)) return;
        const updated = [
          ...current,
          {
            name: modelName,
            is_visible: true,
            max_input_tokens: null,
            supports_image_input: false,
            supports_reasoning: false,
          },
        ];
        formikProps.setFieldValue("model_configurations", updated);
        if (!formikProps.values.test_model_name) {
          formikProps.setFieldValue("test_model_name", modelName);
        }
      }}
    />
  );
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
  onSuccess,
}: LLMProviderFormProps) {
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();

  const onClose = () => onOpenChange?.(false);

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
    <ModalWrapper
      providerName={LLMProviderName.AZURE}
      llmProvider={existingLlmProvider}
      onClose={onClose}
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={async (values, { setSubmitting, setStatus }) => {
        const processedValues = processValues(values);

        await submitProvider({
          analyticsSource: isOnboarding
            ? LLMProviderConfiguredSource.CHAT_ONBOARDING
            : LLMProviderConfiguredSource.ADMIN_PAGE,
          providerName: LLMProviderName.AZURE,
          values: processedValues,
          initialValues,
          existingLlmProvider,
          shouldMarkAsDefault,
          setStatus,
          setSubmitting,
          onClose,
          onSuccess: async () => {
            if (onSuccess) {
              await onSuccess();
            } else {
              await refreshLlmProviderCaches(mutate);
              toast.success(
                existingLlmProvider
                  ? "Provider updated successfully!"
                  : "Provider enabled successfully!"
              );
            }
          },
        });
      }}
    >
      <InputPadder>
        <InputVertical
          withLabel="target_uri"
          title="Target URI"
          subDescription="Paste your endpoint target URI from Azure OpenAI (including API endpoint base, deployment name, and API version)."
        >
          <InputTypeInField
            name="target_uri"
            placeholder="https://your-resource.cognitiveservices.azure.com/openai/deployments/deployment-name/chat/completions?api-version=2025-01-01-preview"
          />
        </InputVertical>
      </InputPadder>

      <APIKeyField providerName="Azure" />

      {!isOnboarding && (
        <>
          <InputDivider />
          <DisplayNameField disabled={!!existingLlmProvider} />
        </>
      )}

      <InputDivider />
      <AzureModelSelection />

      {!isOnboarding && (
        <>
          <InputDivider />
          <ModelAccessField />
        </>
      )}
    </ModalWrapper>
  );
}
