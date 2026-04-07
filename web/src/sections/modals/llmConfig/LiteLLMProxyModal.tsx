"use client";

import { useState, useEffect } from "react";
import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import * as InputLayouts from "@/layouts/input-layouts";
import {
  LLMProviderFormProps,
  LLMProviderName,
  LLMProviderView,
  ModelConfiguration,
} from "@/interfaces/llm";
import { fetchLiteLLMProxyModels } from "@/app/admin/configuration/llm/utils";
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
  APIBaseField,
  ModelSelectionField,
  DisplayNameField,
  ModelAccessField,
  ModalWrapper,
} from "@/sections/modals/llmConfig/shared";
import { toast } from "@/hooks/useToast";

const DEFAULT_API_BASE = "http://localhost:4000";

interface LiteLLMProxyModalValues extends BaseLLMFormValues {
  api_key: string;
  api_base: string;
}

interface LiteLLMProxyModalInternalsProps {
  existingLlmProvider: LLMProviderView | undefined;
  fetchedModels: ModelConfiguration[];
  setFetchedModels: (models: ModelConfiguration[]) => void;
  modelConfigurations: ModelConfiguration[];
  isOnboarding: boolean;
}

function LiteLLMProxyModalInternals({
  existingLlmProvider,
  fetchedModels,
  setFetchedModels,
  modelConfigurations,
  isOnboarding,
}: LiteLLMProxyModalInternalsProps) {
  const formikProps = useFormikContext<LiteLLMProxyModalValues>();
  const currentModels =
    fetchedModels.length > 0
      ? fetchedModels
      : existingLlmProvider?.model_configurations || modelConfigurations;

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
    setFetchedModels(models);
  };

  // Auto-fetch models on initial load when editing an existing provider
  useEffect(() => {
    if (existingLlmProvider && !isFetchDisabled) {
      handleFetchModels().catch((err) => {
        toast.error(
          err instanceof Error ? err.message : "Failed to fetch models"
        );
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      <APIBaseField
        subDescription="The base URL for your LiteLLM Proxy server."
        placeholder="https://your-litellm-proxy.com"
      />

      <APIKeyField providerName="LiteLLM Proxy" />

      {!isOnboarding && (
        <>
          <InputLayouts.FieldSeparator />
          <DisplayNameField disabled={!!existingLlmProvider} />
        </>
      )}

      <InputLayouts.FieldSeparator />
      <ModelSelectionField
        modelConfigurations={currentModels}
        recommendedDefaultModel={null}
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

export default function LiteLLMProxyModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  onOpenChange,
  defaultModelName,
  onboardingState,
  onboardingActions,
  llmDescriptor,
}: LLMProviderFormProps) {
  const [fetchedModels, setFetchedModels] = useState<ModelConfiguration[]>([]);
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();
  const { wellKnownLLMProvider } = useWellKnownLLMProvider(
    LLMProviderName.LITELLM_PROXY
  );

  const onClose = () => onOpenChange?.(false);

  const modelConfigurations = buildAvailableModelConfigurations(
    existingLlmProvider,
    wellKnownLLMProvider ?? llmDescriptor
  );

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
            setStatus,
            mutate,
            onClose,
            setSubmitting,
          });
        }
      }}
    >
      <LiteLLMProxyModalInternals
        existingLlmProvider={existingLlmProvider}
        fetchedModels={fetchedModels}
        setFetchedModels={setFetchedModels}
        modelConfigurations={modelConfigurations}
        isOnboarding={isOnboarding}
      />
    </ModalWrapper>
  );
}
