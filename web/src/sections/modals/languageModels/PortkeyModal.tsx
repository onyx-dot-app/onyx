"use client";

import { useTranslations } from "next-intl";
import { useEffect, useRef } from "react";
import { markdown } from "@opal/utils";
import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import { InputDivider, toast } from "@opal/layouts";
import { Tabs, Text, Button } from "@opal/components";
import { SvgHistory } from "@opal/icons";
import {
  LLMProviderFormProps,
  LLMProviderName,
  LLMProviderView,
  PortkeyApiMode,
} from "@/lib/languageModels/types";
import { fetchPortkeyModels } from "@/lib/languageModels/svc";
import {
  useInitialValues,
  buildValidationSchema,
  BaseLLMFormValues,
  withFetchedModels,
} from "@/sections/modals/languageModels/utils";
import { submitProvider } from "@/sections/modals/languageModels/svc";
import { LLMProviderConfiguredSource } from "@/lib/analytics/utils";
import {
  APIBaseField,
  APIKeyField,
  ModelSelectionField,
  DisplayNameField,
  ModelAccessField,
  ModalWrapper,
} from "@/sections/modals/languageModels/shared";
import { refreshLlmProviderCaches } from "@/lib/languageModels/cache";

const DEFAULT_API_BASE_OPENAI = "https://api.portkey.ai/v1";
const DEFAULT_API_BASE_ANTHROPIC = "https://api.portkey.ai";
const DEFAULT_API_MODE: PortkeyApiMode = "chat_completions";
const PORTKEY_API_MODE_KEY = "portkey_api_mode";
const DEFAULT_DISPLAY_NAME = "Portkey Gateway";

// Switching modes replaces these, but leaves a self-hosted base alone.
const KNOWN_DEFAULT_BASES = new Set<string>([
  DEFAULT_API_BASE_OPENAI,
  DEFAULT_API_BASE_ANTHROPIC,
  "",
]);

function defaultBaseForMode(mode: PortkeyApiMode): string {
  return mode === "messages"
    ? DEFAULT_API_BASE_ANTHROPIC
    : DEFAULT_API_BASE_OPENAI;
}

/** Message keys under the `admin.languageModels.modals` namespace. */
const API_MODE_TABS = [
  {
    value: "chat_completions",
    titleKey: "portkey.apiMode.chatCompletions.label",
    subtitleKey: "portkey.apiMode.chatCompletions.caption",
  },
  {
    value: "responses",
    titleKey: "portkey.apiMode.responses.label",
    subtitleKey: "portkey.apiMode.responses.caption",
  },
  {
    value: "messages",
    titleKey: "portkey.apiMode.messages.label",
    subtitleKey: "portkey.apiMode.messages.caption",
  },
] as const satisfies readonly {
  value: PortkeyApiMode;
  titleKey: string;
  subtitleKey: string;
}[];

interface PortkeyModalValues extends BaseLLMFormValues {
  api_key: string;
  api_base: string;
}

interface PortkeyModalInternalsProps {
  existingLlmProvider: LLMProviderView | undefined;
  isOnboarding: boolean;
}

function PortkeyModalInternals({
  existingLlmProvider,
  isOnboarding,
}: PortkeyModalInternalsProps) {
  const t = useTranslations("admin.languageModels.modals");
  const formikProps = useFormikContext<PortkeyModalValues>();
  const { setFieldValue, setValues, values } = formikProps;

  const mode =
    (values.custom_config?.[PORTKEY_API_MODE_KEY] as
      | PortkeyApiMode
      | undefined) ?? DEFAULT_API_MODE;
  const modeDefaultBase = defaultBaseForMode(mode);
  const isFetchDisabled = !values.api_base;
  const isBaseDefault = values.api_base === modeDefaultBase;

  const handleModeChange = (next: PortkeyApiMode) => {
    setFieldValue("custom_config", { [PORTKEY_API_MODE_KEY]: next });
    if (KNOWN_DEFAULT_BASES.has(values.api_base)) {
      setFieldValue("api_base", defaultBaseForMode(next));
    }
  };

  const handleFetchModels = async () => {
    const { models, error } = await fetchPortkeyModels({
      api_base: values.api_base,
      api_key: values.api_key || undefined,
      provider_id: existingLlmProvider?.id ?? undefined,
    });
    if (error) {
      throw new Error(error);
    }
    setValues(withFetchedModels(models));
  };

  // Refetch once on open so an edit's picker matches the "add" view.
  const autoRefetched = useRef(false);
  useEffect(() => {
    if (autoRefetched.current || !existingLlmProvider?.id) return;
    if (!values.api_base) return;
    autoRefetched.current = true;
    fetchPortkeyModels({
      api_base: values.api_base,
      api_key: values.api_key || undefined,
      provider_id: existingLlmProvider.id,
    })
      .then(({ models }) => {
        if (models.length > 0) {
          setValues(withFetchedModels(models));
        }
      })
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      <Tabs
        value={mode}
        onValueChange={(next) => handleModeChange(next as PortkeyApiMode)}
      >
        <Tabs.List>
          {API_MODE_TABS.map((tab) => (
            <Tabs.Trigger key={tab.value} value={tab.value}>
              <div className="flex flex-col items-start">
                <Text font="main-ui-action" color="inherit">
                  {t(tab.titleKey)}
                </Text>
                <Text font="secondary-body" color="text-03">
                  {t(tab.subtitleKey)}
                </Text>
              </div>
            </Tabs.Trigger>
          ))}
        </Tabs.List>
      </Tabs>

      <APIBaseField
        subDescription={t("portkey.apiBaseField.description")}
        placeholder={t("portkey.apiBaseField.placeholder")}
        rightChildren={
          isBaseDefault ? undefined : (
            <Button
              icon={SvgHistory}
              prominence="tertiary"
              size="xs"
              tooltip={t("portkey.restoreDefaultButton.tooltip")}
              aria-label={t("portkey.restoreDefaultButton.ariaLabel")}
              onClick={() => setFieldValue("api_base", modeDefaultBase)}
            />
          )
        }
      />

      <APIKeyField
        subDescription={markdown(t("portkey.apiKeyField.description"))}
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
        emptyMessage={t("portkey.models.empty.title")}
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

export default function PortkeyModal({
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

  const initialValues: PortkeyModalValues = useInitialValues(
    isOnboarding,
    LLMProviderName.PORTKEY,
    existingLlmProvider
  ) as PortkeyModalValues;

  // useInitialValues drops custom_config, so seed it for submitProvider's
  // custom_config_changed diff (mirrors CustomModal).
  const initialMode =
    (existingLlmProvider?.custom_config?.[PORTKEY_API_MODE_KEY] as
      | PortkeyApiMode
      | undefined) ?? DEFAULT_API_MODE;
  initialValues.custom_config = { [PORTKEY_API_MODE_KEY]: initialMode };

  if (!initialValues.api_base) {
    initialValues.api_base = defaultBaseForMode(initialMode);
  }
  if (!isOnboarding && !initialValues.name) {
    initialValues.name = DEFAULT_DISPLAY_NAME;
  }

  const validationSchema = buildValidationSchema(t, isOnboarding, {
    apiBase: true,
    apiKey: true,
  });

  return (
    <ModalWrapper
      providerName={LLMProviderName.PORTKEY}
      llmProvider={existingLlmProvider}
      onClose={onClose}
      description={t("portkey.description")}
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={async (values, { setSubmitting, setStatus }) => {
        await submitProvider({
          t,
          analyticsSource:
            analyticsSource ??
            (isOnboarding
              ? LLMProviderConfiguredSource.CHAT_ONBOARDING
              : LLMProviderConfiguredSource.ADMIN_PAGE),
          providerName: LLMProviderName.PORTKEY,
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
                  ? t("toasts.providerUpdated")
                  : t("toasts.providerEnabled")
              );
            }
          },
        });
      }}
    >
      <PortkeyModalInternals
        existingLlmProvider={existingLlmProvider}
        isOnboarding={isOnboarding}
      />
    </ModalWrapper>
  );
}
