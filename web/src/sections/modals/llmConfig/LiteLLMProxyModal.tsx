"use client";

import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import { InputDivider } from "@opal/layouts";
import {
  LLMProviderFormProps,
  LLMProviderName,
  LLMProviderView,
} from "@/interfaces/llm";
import { fetchLiteLLMProxyModels } from "@/lib/llmConfig/svc";
import {
  useInitialValues,
  buildValidationSchema,
  BaseLLMFormValues,
  mergeFetchedModelConfigurations,
} from "@/sections/modals/llmConfig/utils";
import { submitProvider } from "@/sections/modals/llmConfig/svc";
import { LLMProviderConfiguredSource } from "@/lib/analytics";
import {
  APIKeyField,
  APIBaseField,
  ModelSelectionField,
  DisplayNameField,
  ModelAccessField,
  ModalWrapper,
} from "@/sections/modals/llmConfig/shared";
import { toast } from "@/hooks/useToast";
import { refreshLlmProviderCaches } from "@/lib/llmConfig/cache";

const DEFAULT_API_BASE = "http://localhost:4000";

interface LiteLLMProxyModalValues extends BaseLLMFormValues {
  api_key: string;
  api_base: string;
}

interface LiteLLMProxyModalInternalsProps {
  existingLlmProvider: LLMProviderView | undefined;
  isOnboarding: boolean;
}

function LiteLLMProxyModalInternals({
  existingLlmProvider,
  isOnboarding,
}: LiteLLMProxyModalInternalsProps) {
  const formikProps = useFormikContext<LiteLLMProxyModalValues>();

  const isFetchDisabled =
    !formikProps.values.api_base || !formikProps.values.api_key;

  const handleFetchModels = async () => {
    const { models, error } = await fetchLiteLLMProxyModels({
      api_base: formikProps.values.api_base,
      api_key: formikProps.values.api_key,
      provider_name: existingLlmProvider?.name,
    });
    if (error) {
      throw new Error(error);
    }
    formikProps.setFieldValue(
      "model_configurations",
      mergeFetchedModelConfigurations(
        models,
        formikProps.values.model_configurations
      )
    );
  };

  return (
    <>
      <APIBaseField
        subDescription="The base URL for your LiteLLM Proxy server."
        placeholder="https://your-litellm-proxy.com"
      />

      <APIKeyField providerName="LiteLLM Proxy" />

      {!isOnboarding && (
        <>
          <InputDivider />
          <DisplayNameField disabled={!!existingLlmProvider} />
        </>
      )}

      <InputDivider />
      <ModelSelectionField
        shouldShowAutoUpdateToggle={false}
        onRefetch={isFetchDisabled ? undefined : handleFetchModels}
      />

      {!isOnboarding && (
        <>
          <InputDivider />
          <ModelAccessField />
        </>
      )}
    </>
  );
}

export default function LiteLLMProxyModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  onOpenChange,
  onSuccess,
}: LLMProviderFormProps) {
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();

  const onClose = () => onOpenChange?.(false);

  const initialValues: LiteLLMProxyModalValues = {
    ...useInitialValues(
      isOnboarding,
      LLMProviderName.LITELLM_PROXY,
      existingLlmProvider
    ),
    api_base: existingLlmProvider?.api_base ?? DEFAULT_API_BASE,
  } as LiteLLMProxyModalValues;

  const validationSchema = buildValidationSchema(isOnboarding, {
    apiKey: true,
    apiBase: true,
  });

  return (
    <ModalWrapper
      providerName={LLMProviderName.LITELLM_PROXY}
      llmProvider={existingLlmProvider}
      onClose={onClose}
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={async (values, { setSubmitting, setStatus }) => {
        await submitProvider({
          analyticsSource: isOnboarding
            ? LLMProviderConfiguredSource.CHAT_ONBOARDING
            : LLMProviderConfiguredSource.ADMIN_PAGE,
          providerName: LLMProviderName.LITELLM_PROXY,
          values,
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
      <LiteLLMProxyModalInternals
        existingLlmProvider={existingLlmProvider}
        isOnboarding={isOnboarding}
      />
    </ModalWrapper>
  );
}
