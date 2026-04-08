"use client";

import * as Yup from "yup";
import { Dispatch, SetStateAction, useMemo, useState } from "react";
import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import * as InputLayouts from "@/layouts/input-layouts";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import {
  LLMProviderFormProps,
  LLMProviderName,
  LLMProviderView,
} from "@/interfaces/llm";
import {
  useInitialValues,
  buildValidationSchema,
  BaseLLMFormValues,
} from "@/sections/modals/llmConfig/utils";
import { submitProvider } from "@/sections/modals/llmConfig/svc";
import { LLMProviderConfiguredSource } from "@/lib/analytics";
import {
  ModelSelectionField,
  DisplayNameField,
  ModelAccessField,
  ModalWrapper,
} from "@/sections/modals/llmConfig/shared";
import { fetchOllamaModels } from "@/app/admin/configuration/llm/utils";
import Tabs from "@/refresh-components/Tabs";
import { Card } from "@opal/components";
import { toast } from "@/hooks/useToast";
import { refreshLlmProviderCaches } from "@/lib/llmConfig/cache";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import useOnMount from "@/hooks/useOnMount";

const DEFAULT_API_BASE = "http://127.0.0.1:11434";
const CLOUD_API_BASE = "https://ollama.com";

enum Tab {
  TAB_SELF_HOSTED = "self-hosted",
  TAB_CLOUD = "cloud",
}

interface OllamaModalValues extends BaseLLMFormValues {
  api_base: string;
  custom_config: {
    OLLAMA_API_KEY?: string;
  };
}

interface OllamaModalInternalsProps {
  existingLlmProvider: LLMProviderView | undefined;
  isOnboarding: boolean;
  tab: Tab;
  setTab: Dispatch<SetStateAction<Tab>>;
}

function OllamaModalInternals({
  existingLlmProvider,
  isOnboarding,
  tab,
  setTab,
}: OllamaModalInternalsProps) {
  const formikProps = useFormikContext<OllamaModalValues>();

  const isFetchDisabled = useMemo(
    () =>
      tab === Tab.TAB_SELF_HOSTED
        ? !formikProps.values.api_base
        : !formikProps.values.custom_config.OLLAMA_API_KEY,
    [tab, formikProps]
  );

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
    formikProps.setFieldValue("model_configurations", models);
  };

  // Auto-fetch models on initial load when editing an existing provider
  useOnMount(() => {
    if (existingLlmProvider) {
      handleFetchModels().catch((err) => {
        toast.error(
          err instanceof Error ? err.message : "Failed to fetch models"
        );
      });
    }
  });

  return (
    <>
      <Card background="light" border="none" padding="sm">
        <Tabs value={tab} onValueChange={(value) => setTab(value as Tab)}>
          <Tabs.List>
            <Tabs.Trigger value={Tab.TAB_SELF_HOSTED}>
              Self-hosted Ollama
            </Tabs.Trigger>
            <Tabs.Trigger value={Tab.TAB_CLOUD}>Ollama Cloud</Tabs.Trigger>
          </Tabs.List>
          <Tabs.Content value={Tab.TAB_SELF_HOSTED} padding={0}>
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

          <Tabs.Content value={Tab.TAB_CLOUD}>
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

export default function OllamaModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  onOpenChange,
  onSuccess,
}: LLMProviderFormProps) {
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();
  const apiKey = existingLlmProvider?.custom_config?.OLLAMA_API_KEY;
  const defaultTab =
    existingLlmProvider && !!apiKey ? Tab.TAB_CLOUD : Tab.TAB_SELF_HOSTED;
  const [tab, setTab] = useState<Tab>(defaultTab);

  const onClose = () => onOpenChange?.(false);

  const initialValues: OllamaModalValues = {
    ...useInitialValues(
      isOnboarding,
      LLMProviderName.OLLAMA_CHAT,
      existingLlmProvider
    ),
    api_base: existingLlmProvider?.api_base ?? DEFAULT_API_BASE,
    custom_config: {
      OLLAMA_API_KEY: apiKey,
    },
  } as OllamaModalValues;

  const validationSchema = useMemo(
    () =>
      buildValidationSchema(isOnboarding, {
        apiBase: tab === Tab.TAB_SELF_HOSTED,
        extra:
          tab === Tab.TAB_CLOUD
            ? {
                custom_config: Yup.object({
                  OLLAMA_API_KEY: Yup.string().required("API Key is required"),
                }),
              }
            : undefined,
      }),
    [tab, isOnboarding]
  );

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

        await submitProvider({
          analyticsSource: isOnboarding
            ? LLMProviderConfiguredSource.CHAT_ONBOARDING
            : LLMProviderConfiguredSource.ADMIN_PAGE,
          providerName: LLMProviderName.OLLAMA_CHAT,
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
      <OllamaModalInternals
        existingLlmProvider={existingLlmProvider}
        isOnboarding={isOnboarding}
        tab={tab}
        setTab={setTab}
      />
    </ModalWrapper>
  );
}
