"use client";

import { useState, useEffect } from "react";
import { markdown } from "@opal/utils";
import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import * as InputLayouts from "@/layouts/input-layouts";
import {
  LLMProviderFormProps,
  LLMProviderName,
  LLMProviderView,
  ModelConfiguration,
} from "@/interfaces/llm";
import { fetchOpenAICompatibleModels } from "@/app/admin/configuration/llm/utils";
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
  APIBaseField,
  APIKeyField,
  ModelSelectionField,
  DisplayNameField,
  ModelAccessField,
  ModalWrapper,
} from "@/sections/modals/llmConfig/shared";
import { toast } from "@/hooks/useToast";

interface OpenAICompatibleModalValues extends BaseLLMFormValues {
  api_key: string;
  api_base: string;
}

interface OpenAICompatibleModalInternalsProps {
  existingLlmProvider: LLMProviderView | undefined;
  fetchedModels: ModelConfiguration[];
  setFetchedModels: (models: ModelConfiguration[]) => void;
  modelConfigurations: ModelConfiguration[];
  isOnboarding: boolean;
}

function OpenAICompatibleModalInternals({
  existingLlmProvider,
  fetchedModels,
  setFetchedModels,
  modelConfigurations,
  isOnboarding,
}: OpenAICompatibleModalInternalsProps) {
  const formikProps = useFormikContext<OpenAICompatibleModalValues>();
  const currentModels =
    fetchedModels.length > 0
      ? fetchedModels
      : existingLlmProvider?.model_configurations || modelConfigurations;

  const isFetchDisabled = !formikProps.values.api_base;

  const handleFetchModels = async () => {
    const { models, error } = await fetchOpenAICompatibleModels({
      api_base: formikProps.values.api_base,
      api_key: formikProps.values.api_key || undefined,
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
        subDescription="The base URL of your OpenAI-compatible server."
        placeholder="http://localhost:8000/v1"
      />

      <APIKeyField
        optional
        subDescription={markdown(
          "Provide an API key if your server requires authentication."
        )}
      />

      {!isOnboarding && (
        <>
          <InputLayouts.FieldSeparator />
          <DisplayNameField disabled={!!existingLlmProvider} />
        </>
      )}

      <InputLayouts.FieldSeparator />
      <ModelSelectionField
        modelConfigurations={currentModels}
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

export default function OpenAICompatibleModal({
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
    LLMProviderName.OPENAI_COMPATIBLE
  );

  const onClose = () => onOpenChange?.(false);

  const modelConfigurations = buildAvailableModelConfigurations(
    existingLlmProvider,
    wellKnownLLMProvider ?? llmDescriptor
  );

  const initialValues = useInitialValues(
    isOnboarding,
    LLMProviderName.OPENAI_COMPATIBLE,
    existingLlmProvider
  ) as OpenAICompatibleModalValues;

  const validationSchema = buildValidationSchema(isOnboarding, {
    apiBase: true,
  });

  return (
    <ModalWrapper
      providerName={LLMProviderName.OPENAI_COMPATIBLE}
      llmProvider={existingLlmProvider}
      onClose={onClose}
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={async (values, { setSubmitting, setStatus }) => {
        if (isOnboarding && onboardingState && onboardingActions) {
          const modelConfigsToUse =
            fetchedModels.length > 0 ? fetchedModels : [];

          await submitOnboardingProvider({
            providerName: LLMProviderName.OPENAI_COMPATIBLE,
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
            providerName: LLMProviderName.OPENAI_COMPATIBLE,
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
      <OpenAICompatibleModalInternals
        existingLlmProvider={existingLlmProvider}
        fetchedModels={fetchedModels}
        setFetchedModels={setFetchedModels}
        modelConfigurations={modelConfigurations}
        isOnboarding={isOnboarding}
      />
    </ModalWrapper>
  );
}
