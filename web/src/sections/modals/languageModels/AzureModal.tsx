"use client";

import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import { InputDivider, InputPadder, InputVertical, toast } from "@opal/layouts";
import {
  LLMProviderFormProps,
  LLMProviderName,
} from "@/lib/languageModels/types";
import * as Yup from "yup";
import {
  useInitialValues,
  buildValidationSchema,
  BaseLLMFormValues,
  LlmModalsTranslator,
} from "@/sections/modals/languageModels/utils";
import { submitProvider } from "@/sections/modals/languageModels/svc";
import { LLMProviderConfiguredSource } from "@/lib/analytics/utils";
import {
  APIKeyField,
  DisplayNameField,
  ModelAccessField,
  ModelSelectionField,
  ModalWrapper,
} from "@/sections/modals/languageModels/shared";
import {
  buildTargetUri,
  isValidAzureTargetUri,
  parseAzureTargetUri,
} from "@/lib/azureTargetUri";
import { refreshLlmProviderCaches } from "@/lib/languageModels/cache";

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

const processValues = (
  values: AzureModalValues,
  t: LlmModalsTranslator
): AzureModalValues => {
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
      toast.warning(t("azure.toasts.targetUriParseFailed"));
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
  analyticsSource,
}: LLMProviderFormProps) {
  const t = useTranslations("admin.languageModels.modals");
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

  const validationSchema = buildValidationSchema(t, isOnboarding, {
    apiKey: true,
    extra: {
      target_uri: Yup.string()
        .required(t("azure.validation.targetUriRequired"))
        .test(
          "valid-target-uri",
          t("azure.validation.targetUriInvalid"),
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
        const processedValues = processValues(values, t);

        await submitProvider({
          t,
          analyticsSource:
            analyticsSource ??
            (isOnboarding
              ? LLMProviderConfiguredSource.CHAT_ONBOARDING
              : LLMProviderConfiguredSource.ADMIN_PAGE),
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
                  ? t("toasts.providerUpdated")
                  : t("toasts.providerEnabled")
              );
            }
          },
        });
      }}
    >
      <InputPadder>
        <InputVertical
          withLabel="target_uri"
          title={t("azure.targetUriField.title")}
          subDescription={t("azure.targetUriField.description")}
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
          <DisplayNameField />
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
