"use client";

import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import * as InputLayouts from "@/layouts/input-layouts";
import {
  LLMProviderFormProps,
  LLMProviderName,
  LLMProviderView,
} from "@/interfaces/llm";
import { fetchOpenRouterModels } from "@/lib/llmConfig/svc";
import {
  useInitialValues,
  buildValidationSchema,
  BaseLLMFormValues,
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

const DEFAULT_API_BASE = "https://openrouter.ai/api/v1";

interface OpenRouterModalValues extends BaseLLMFormValues {
  api_key: string;
  api_base: string;
}

interface OpenRouterModalInternalsProps {
  existingLlmProvider: LLMProviderView | undefined;
  isOnboarding: boolean;
}

function OpenRouterModalInternals({
  existingLlmProvider,
  isOnboarding,
}: OpenRouterModalInternalsProps) {
  const formikProps = useFormikContext<OpenRouterModalValues>();

  const isFetchDisabled =
    !formikProps.values.api_base || !formikProps.values.api_key;

  const handleFetchModels = async () => {
    const { models, error } = await fetchOpenRouterModels({
      api_base: formikProps.values.api_base,
      api_key: formikProps.values.api_key,
      provider_name: existingLlmProvider?.name,
    });
    if (error) {
      throw new Error(error);
    }
    formikProps.setFieldValue("model_configurations", models);
  };

  return (
    <>
      <APIBaseField
        subDescription="Paste your OpenRouter-compatible endpoint URL or use OpenRouter API directly."
        placeholder="Your OpenRouter base URL"
      />

      <APIKeyField providerName="OpenRouter" />

      {!isOnboarding && (
        <>
          <InputLayouts.FieldSeparator />
          <DisplayNameField disabled={!!existingLlmProvider} />
        </>
      )}

      <InputLayouts.FieldSeparator />
      <ModelSelectionField
        shouldShowAutoUpdateToggle={false}
        onRefetch={isFetchDisabled ? undefined : handleFetchModels}
      />

      {!isOnboarding && (
        <>
          <InputLayouts.FieldSeparator />
          <ModelAccessField />
        </>
      )}
    </>
  );
}

export default function OpenRouterModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  onOpenChange,
  onSuccess,
}: LLMProviderFormProps) {
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();

  const onClose = () => onOpenChange?.(false);

  const initialValues: OpenRouterModalValues = {
    ...useInitialValues(
      isOnboarding,
      LLMProviderName.OPENROUTER,
      existingLlmProvider
    ),
    api_base: existingLlmProvider?.api_base ?? DEFAULT_API_BASE,
  } as OpenRouterModalValues;

  const validationSchema = buildValidationSchema(isOnboarding, {
    apiKey: true,
    apiBase: true,
  });

  return (
    <ModalWrapper
      providerName={LLMProviderName.OPENROUTER}
      llmProvider={existingLlmProvider}
      onClose={onClose}
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={async (values, { setSubmitting, setStatus }) => {
        await submitProvider({
          analyticsSource: isOnboarding
            ? LLMProviderConfiguredSource.CHAT_ONBOARDING
            : LLMProviderConfiguredSource.ADMIN_PAGE,
          providerName: LLMProviderName.OPENROUTER,
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
      <OpenRouterModalInternals
        existingLlmProvider={existingLlmProvider}
        isOnboarding={isOnboarding}
      />
    </ModalWrapper>
  );
}
