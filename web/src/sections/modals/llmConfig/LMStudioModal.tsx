"use client";

import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import * as InputLayouts from "@/layouts/input-layouts";
import {
  LLMProviderFormProps,
  LLMProviderName,
  LLMProviderView,
} from "@/interfaces/llm";
import {
  useInitialValues,
  buildValidationSchema,
  BaseLLMFormValues as BaseLLMModalValues,
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
import { fetchModels } from "@/app/admin/configuration/llm/utils";
import { toast } from "@/hooks/useToast";
import { refreshLlmProviderCaches } from "@/lib/llmConfig/cache";

const DEFAULT_API_BASE = "http://localhost:1234";

interface LMStudioModalValues extends BaseLLMModalValues {
  api_base: string;
  custom_config: {
    LM_STUDIO_API_KEY?: string;
  };
}

interface LMStudioModalInternalsProps {
  existingLlmProvider: LLMProviderView | undefined;
  isOnboarding: boolean;
}

function LMStudioModalInternals({
  existingLlmProvider,
  isOnboarding,
}: LMStudioModalInternalsProps) {
  const formikProps = useFormikContext<LMStudioModalValues>();

  const isFetchDisabled = !formikProps.values.api_base;

  const handleFetchModels = async () => {
    const apiKey = formikProps.values.custom_config?.LM_STUDIO_API_KEY;
    const initialApiKey = existingLlmProvider?.custom_config?.LM_STUDIO_API_KEY;
    const data = await fetchModels(LLMProviderName.LM_STUDIO, {
      api_base: formikProps.values.api_base,
      custom_config: apiKey ? { LM_STUDIO_API_KEY: apiKey } : {},
      api_key_changed: apiKey !== initialApiKey,
      name: existingLlmProvider?.name,
    });
    if (data.error) {
      throw new Error(data.error);
    }
    formikProps.setFieldValue("model_configurations", data.models);
  };

  return (
    <>
      <APIBaseField
        subDescription="The base URL for your LM Studio server."
        placeholder="Your LM Studio API base URL"
      />

      <APIKeyField
        name="custom_config.LM_STUDIO_API_KEY"
        optional
        subDescription="Optional API key if your LM Studio server requires authentication."
      />

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

export default function LMStudioModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  onOpenChange,
  onSuccess,
}: LLMProviderFormProps) {
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();

  const onClose = () => onOpenChange?.(false);

  const initialValues: LMStudioModalValues = {
    ...useInitialValues(
      isOnboarding,
      LLMProviderName.LM_STUDIO,
      existingLlmProvider
    ),
    api_base: existingLlmProvider?.api_base ?? DEFAULT_API_BASE,
    custom_config: {
      LM_STUDIO_API_KEY: existingLlmProvider?.custom_config?.LM_STUDIO_API_KEY,
    },
  } as LMStudioModalValues;

  const validationSchema = buildValidationSchema(isOnboarding, {
    apiBase: true,
  });

  return (
    <ModalWrapper
      providerName={LLMProviderName.LM_STUDIO}
      llmProvider={existingLlmProvider}
      onClose={onClose}
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={async (values, { setSubmitting, setStatus }) => {
        const filteredCustomConfig = Object.fromEntries(
          Object.entries(values.custom_config || {}).filter(([, v]) => v !== "")
        );

        const submitValues = {
          ...values,
          custom_config:
            Object.keys(filteredCustomConfig).length > 0
              ? filteredCustomConfig
              : undefined,
        };

        await submitProvider({
          analyticsSource: isOnboarding
            ? LLMProviderConfiguredSource.CHAT_ONBOARDING
            : LLMProviderConfiguredSource.ADMIN_PAGE,
          providerName: LLMProviderName.LM_STUDIO,
          values: submitValues,
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
      <LMStudioModalInternals
        existingLlmProvider={existingLlmProvider}
        isOnboarding={isOnboarding}
      />
    </ModalWrapper>
  );
}
