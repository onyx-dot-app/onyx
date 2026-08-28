"use client";

import { useTranslations } from "next-intl";
import { Dispatch, SetStateAction, useMemo, useState } from "react";
import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import { InputDivider, InputVertical, toast } from "@opal/layouts";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import {
  LLMProviderFormProps,
  LLMProviderName,
  LLMProviderView,
} from "@/lib/languageModels/types";
import {
  useInitialValues,
  buildValidationSchema,
  BaseLLMFormValues,
  withFetchedModels,
} from "@/sections/modals/languageModels/utils";
import { submitProvider } from "@/sections/modals/languageModels/svc";
import { LLMProviderConfiguredSource } from "@/lib/analytics/utils";
import {
  ModelSelectionField,
  DisplayNameField,
  ModelAccessField,
  ModalWrapper,
  useApiBaseSubDescription,
} from "@/sections/modals/languageModels/shared";
import { fetchOllamaModels } from "@/lib/languageModels/svc";
import { Card, Tabs } from "@opal/components";
import { refreshLlmProviderCaches } from "@/lib/languageModels/cache";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import { useSettings } from "@/lib/settings/hooks";
const CLOUD_API_BASE = "https://ollama.com";

enum Tab {
  TAB_SELF_HOSTED = "self-hosted",
  TAB_CLOUD = "cloud",
}

interface OllamaModalValues extends BaseLLMFormValues {
  api_base: string;
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
  const t = useTranslations("admin.languageModels.modals");
  const formikProps = useFormikContext<OllamaModalValues>();
  const apiBaseSubDescription = useApiBaseSubDescription(
    t("ollama.apiBaseField.description")
  );

  const isFetchDisabled = useMemo(
    () =>
      tab === Tab.TAB_SELF_HOSTED
        ? !formikProps.values.api_base
        : !formikProps.values.api_key,
    [tab, formikProps]
  );

  const handleFetchModels = async (signal?: AbortSignal) => {
    // Only Ollama cloud accepts API key
    const apiBase = formikProps.values.api_key
      ? CLOUD_API_BASE
      : formikProps.values.api_base;
    const { models, error } = await fetchOllamaModels({
      api_base: apiBase,
      provider_id: existingLlmProvider?.id ?? undefined,
      signal,
    });
    if (signal?.aborted) return;
    if (error) {
      throw new Error(error);
    }
    formikProps.setValues(withFetchedModels(models));
  };

  return (
    <>
      <Card background="light" border="none" padding={2}>
        <Tabs value={tab} onValueChange={(value) => setTab(value as Tab)}>
          <Tabs.List>
            <Tabs.Trigger value={Tab.TAB_SELF_HOSTED}>
              {t("ollama.tabs.selfHosted.label")}
            </Tabs.Trigger>
            <Tabs.Trigger value={Tab.TAB_CLOUD}>
              {t("ollama.tabs.cloud.label")}
            </Tabs.Trigger>
          </Tabs.List>
          <div className="pt-4">
            <Tabs.Content value={Tab.TAB_SELF_HOSTED}>
              <InputVertical
                withLabel="api_base"
                title={t("setup.apiBaseField.title")}
                subDescription={apiBaseSubDescription}
              >
                <InputTypeInField
                  name="api_base"
                  placeholder={t("ollama.apiBaseField.placeholder")}
                />
              </InputVertical>
            </Tabs.Content>

            <Tabs.Content value={Tab.TAB_CLOUD}>
              <InputVertical
                withLabel="api_key"
                title={t("setup.apiKeyField.title")}
                subDescription={t("ollama.apiKeyField.description")}
              >
                <PasswordInputTypeInField
                  name="api_key"
                  placeholder={t("ollama.apiKeyField.placeholder")}
                />
              </InputVertical>
            </Tabs.Content>
          </div>
        </Tabs>
      </Card>

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

export default function OllamaModal({
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
  const settings = useSettings();
  const defaultApiBase = settings.is_containerized
    ? "http://host.docker.internal:11434"
    : "http://127.0.0.1:11434";
  const apiKey = existingLlmProvider?.api_key;
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
    api_base: existingLlmProvider?.api_base ?? defaultApiBase,
  } as OllamaModalValues;

  const validationSchema = useMemo(
    () =>
      buildValidationSchema(t, isOnboarding, {
        apiBase: tab === Tab.TAB_SELF_HOSTED,
        apiKey: tab === Tab.TAB_CLOUD,
      }),
    [t, tab, isOnboarding]
  );

  return (
    <ModalWrapper
      providerName={LLMProviderName.OLLAMA_CHAT}
      llmProvider={existingLlmProvider}
      onClose={onClose}
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={async (values, { setSubmitting, setStatus }) => {
        const submitValues = {
          ...values,
          // Ollama Cloud is reached via a fixed base URL; the API key implies it.
          api_base: values.api_key ? CLOUD_API_BASE : values.api_base,
        };

        await submitProvider({
          t,
          analyticsSource:
            analyticsSource ??
            (isOnboarding
              ? LLMProviderConfiguredSource.CHAT_ONBOARDING
              : LLMProviderConfiguredSource.ADMIN_PAGE),
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
                  ? t("toasts.providerUpdated")
                  : t("toasts.providerEnabled")
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
