"use client";

import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import { InputDivider, toast } from "@opal/layouts";
import {
  LLMProviderFormProps,
  LLMProviderName,
  LLMProviderView,
} from "@/lib/languageModels/types";
import {
  useInitialValues,
  buildValidationSchema,
  BaseLLMFormValues as BaseLLMModalValues,
  withFetchedModels,
} from "@/sections/modals/languageModels/utils";
import { submitProvider } from "@/sections/modals/languageModels/svc";
import { LLMProviderConfiguredSource } from "@/lib/analytics/utils";
import {
  APIKeyField,
  APIBaseField,
  ModelSelectionField,
  DisplayNameField,
  ModelAccessField,
  ModalWrapper,
  useApiBaseSubDescription,
} from "@/sections/modals/languageModels/shared";
import { fetchModels } from "@/lib/languageModels/svc";
import { refreshLlmProviderCaches } from "@/lib/languageModels/cache";
import { useSettings } from "@/lib/settings/hooks";

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
  const apiBaseSubDescription = useApiBaseSubDescription(
    "The base URL for your LM Studio server."
  );

  const isFetchDisabled = !formikProps.values.api_base;

  const handleFetchModels = async () => {
    const apiKey = formikProps.values.custom_config?.LM_STUDIO_API_KEY;
    const initialApiKey = existingLlmProvider?.custom_config?.LM_STUDIO_API_KEY;
    const data = await fetchModels(LLMProviderName.LM_STUDIO, {
      api_base: formikProps.values.api_base,
      custom_config: apiKey ? { LM_STUDIO_API_KEY: apiKey } : {},
      api_key_changed: apiKey !== initialApiKey,
      id: existingLlmProvider?.id ?? undefined,
    });
    if (data.error) {
      throw new Error(data.error);
    }
    formikProps.setValues(withFetchedModels(data.models));
  };

  return (
    <>
      <APIBaseField
        subDescription={apiBaseSubDescription}
        placeholder="Your LM Studio API base URL"
      />

      <APIKeyField
        name="custom_config.LM_STUDIO_API_KEY"
        optional
        subDescription="Optional API key if your LM Studio server requires authentication."
      />

      {!isOnboarding && (
        <>
          <InputDivider />
          <DisplayNameField />
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

export default function LMStudioModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  onOpenChange,
  onSuccess,
  analyticsSource,
}: LLMProviderFormProps) {
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();
  const settings = useSettings();
  const defaultApiBase = settings.is_containerized
    ? "http://host.docker.internal:1234"
    : "http://localhost:1234";

  const onClose = () => onOpenChange?.(false);

  const initialValues: LMStudioModalValues = {
    ...useInitialValues(
      isOnboarding,
      LLMProviderName.LM_STUDIO,
      existingLlmProvider
    ),
    api_base: existingLlmProvider?.api_base ?? defaultApiBase,
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
          analyticsSource:
            analyticsSource ??
            (isOnboarding
              ? LLMProviderConfiguredSource.CHAT_ONBOARDING
              : LLMProviderConfiguredSource.ADMIN_PAGE),
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
