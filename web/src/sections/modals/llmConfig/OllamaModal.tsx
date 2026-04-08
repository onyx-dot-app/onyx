"use client";

import { useEffect, useState } from "react";
import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import * as InputLayouts from "@/layouts/input-layouts";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import {
  LLMProviderFormProps,
  LLMProviderName,
  LLMProviderView,
  ModelConfiguration,
} from "@/interfaces/llm";
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
  ModelSelectionField,
  DisplayNameField,
  ModelAccessField,
  ModalWrapper,
} from "@/sections/modals/llmConfig/shared";
import { fetchOllamaModels } from "@/app/admin/configuration/llm/utils";
import Tabs from "@/refresh-components/Tabs";
import { Card } from "@opal/components";
import { toast } from "@/hooks/useToast";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";

const DEFAULT_API_BASE = "http://127.0.0.1:11434";
const CLOUD_API_BASE = "https://ollama.com";
const TAB_SELF_HOSTED = "self-hosted";
const TAB_CLOUD = "cloud";

interface OllamaModalValues extends BaseLLMFormValues {
  api_base: string;
  custom_config: {
    OLLAMA_API_KEY?: string;
  };
}

interface OllamaModalInternalsProps {
  existingLlmProvider: LLMProviderView | undefined;
  fetchedModels: ModelConfiguration[];
  setFetchedModels: (models: ModelConfiguration[]) => void;
  isOnboarding: boolean;
}

function OllamaModalInternals({
  existingLlmProvider,
  fetchedModels,
  setFetchedModels,
  isOnboarding,
}: OllamaModalInternalsProps) {
  const formikProps = useFormikContext<OllamaModalValues>();

  const handleFetchModels = async (signal?: AbortSignal) => {
    // Only Ollama cloud accepts API key
    const apiBase = formikProps.values.custom_config?.OLLAMA_API_KEY
      ? CLOUD_API_BASE
      : formikProps.values.api_base;
    const { models, error } = await fetchOllamaModels({
      api_base: apiBase,
      provider_name: existingLlmProvider?.name,
      signal,
    });
    if (signal?.aborted) return;
    if (error) {
      throw new Error(error);
    }
    setFetchedModels(models);
  };

  // Auto-fetch models on initial load when editing an existing provider
  useEffect(() => {
    if (existingLlmProvider) {
      handleFetchModels().catch((err) => {
        toast.error(
          err instanceof Error ? err.message : "Failed to fetch models"
        );
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const currentModels =
    fetchedModels.length > 0
      ? fetchedModels
      : existingLlmProvider?.model_configurations || [];

  const hasApiKey = !!formikProps.values.custom_config?.OLLAMA_API_KEY;
  const defaultTab =
    existingLlmProvider && hasApiKey ? TAB_CLOUD : TAB_SELF_HOSTED;

  return (
    <>
      <Card background="light" border="none" padding="sm">
        <Tabs defaultValue={defaultTab}>
          <Tabs.List>
            <Tabs.Trigger value={TAB_SELF_HOSTED}>
              Self-hosted Ollama
            </Tabs.Trigger>
            <Tabs.Trigger value={TAB_CLOUD}>Ollama Cloud</Tabs.Trigger>
          </Tabs.List>
          <Tabs.Content value={TAB_SELF_HOSTED} padding={0}>
            <InputLayouts.Vertical
              name="api_base"
              title="API Base URL"
              subDescription="The base URL for your Ollama instance."
            >
              <InputTypeInField
                name="api_base"
                placeholder="Your Ollama API base URL"
              />
            </InputLayouts.Vertical>
          </Tabs.Content>

          <Tabs.Content value={TAB_CLOUD}>
            <InputLayouts.Vertical
              name="custom_config.OLLAMA_API_KEY"
              title="API Key"
              subDescription="Your Ollama Cloud API key."
            >
              <PasswordInputTypeInField
                name="custom_config.OLLAMA_API_KEY"
                placeholder="API Key"
              />
            </InputLayouts.Vertical>
          </Tabs.Content>
        </Tabs>
      </Card>

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
        onRefetch={handleFetchModels}
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

export default function OllamaModal({
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
    LLMProviderName.OLLAMA_CHAT
  );

  const onClose = () => onOpenChange?.(false);

  const modelConfigurations = buildAvailableModelConfigurations(
    existingLlmProvider,
    wellKnownLLMProvider ?? llmDescriptor
  );

  const initialValues: OllamaModalValues = {
    ...useInitialValues(
      isOnboarding,
      LLMProviderName.OLLAMA_CHAT,
      existingLlmProvider
    ),
    api_base: existingLlmProvider?.api_base ?? DEFAULT_API_BASE,
    custom_config: {
      OLLAMA_API_KEY:
        (existingLlmProvider?.custom_config?.OLLAMA_API_KEY as string) ?? "",
    },
  } as OllamaModalValues;

  const validationSchema = buildValidationSchema(isOnboarding, {
    apiBase: true,
  });

  return (
    <ModalWrapper
      providerName={LLMProviderName.OLLAMA_CHAT}
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
          api_base: filteredCustomConfig.OLLAMA_API_KEY
            ? CLOUD_API_BASE
            : values.api_base,
          custom_config:
            Object.keys(filteredCustomConfig).length > 0
              ? filteredCustomConfig
              : undefined,
        };

        if (isOnboarding && onboardingState && onboardingActions) {
          const modelConfigsToUse =
            fetchedModels.length > 0 ? fetchedModels : [];

          await submitOnboardingProvider({
            providerName: LLMProviderName.OLLAMA_CHAT,
            payload: {
              ...submitValues,
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
            providerName: LLMProviderName.OLLAMA_CHAT,
            values: submitValues,
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
      <OllamaModalInternals
        existingLlmProvider={existingLlmProvider}
        fetchedModels={fetchedModels}
        setFetchedModels={setFetchedModels}
        isOnboarding={isOnboarding}
      />
    </ModalWrapper>
  );
}
