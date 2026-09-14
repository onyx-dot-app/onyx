"use client";

import { useTranslations } from "next-intl";
import { markdown } from "@opal/utils";
import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import { InputDivider, toast } from "@opal/layouts";
import { Tabs, Text } from "@opal/components";
import {
  BifrostApiMode,
  LLMProviderFormProps,
  LLMProviderName,
  LLMProviderView,
} from "@/lib/languageModels/types";
import { fetchBifrostModels } from "@/lib/languageModels/svc";
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

const DEFAULT_API_MODE: BifrostApiMode = "chat_completions";
const BIFROST_API_MODE_KEY = "bifrost_api_mode";

const API_MODE_TABS = [
  {
    value: "chat_completions",
    titleKey: "bifrost.apiMode.chatCompletions.label",
    subtitle: "/v1/chat/completions",
  },
  {
    value: "responses",
    titleKey: "bifrost.apiMode.responses.label",
    subtitle: "/v1/responses",
  },
] as const satisfies readonly {
  value: BifrostApiMode;
  titleKey: string;
  subtitle: string;
}[];

interface BifrostModalValues extends BaseLLMFormValues {
  api_key: string;
  api_base: string;
}

interface BifrostModalInternalsProps {
  existingLlmProvider: LLMProviderView | undefined;
  isOnboarding: boolean;
}

function BifrostModalInternals({
  existingLlmProvider,
  isOnboarding,
}: BifrostModalInternalsProps) {
  const t = useTranslations("admin.languageModels.modals");
  const formikProps = useFormikContext<BifrostModalValues>();
  const { setFieldValue, values } = formikProps;

  const mode =
    (values.custom_config?.[BIFROST_API_MODE_KEY] as
      | BifrostApiMode
      | undefined) ?? DEFAULT_API_MODE;

  const isFetchDisabled = !formikProps.values.api_base;

  const handleFetchModels = async () => {
    const { models, error } = await fetchBifrostModels({
      api_base: formikProps.values.api_base,
      api_key: formikProps.values.api_key || undefined,
      provider_id: existingLlmProvider?.id ?? undefined,
    });
    if (error) {
      throw new Error(error);
    }
    formikProps.setValues(withFetchedModels(models));
  };

  return (
    <>
      <Tabs
        value={mode}
        onValueChange={(next) =>
          setFieldValue("custom_config", {
            ...values.custom_config,
            [BIFROST_API_MODE_KEY]: next as BifrostApiMode,
          })
        }
      >
        <Tabs.List>
          {API_MODE_TABS.map((tab) => (
            <Tabs.Trigger key={tab.value} value={tab.value}>
              <div className="flex flex-col items-start">
                <Text font="main-ui-action" color="inherit">
                  {t(tab.titleKey)}
                </Text>
                <Text font="secondary-body" color="text-03">
                  {tab.subtitle}
                </Text>
              </div>
            </Tabs.Trigger>
          ))}
        </Tabs.List>
      </Tabs>

      <APIBaseField
        subDescription={t("bifrost.apiBaseField.description")}
        placeholder="https://your-bifrost-gateway.com/v1"
      />

      <APIKeyField
        optional
        subDescription={markdown(t("bifrost.apiKeyField.description"))}
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

export default function BifrostModal({
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

  const initialValues: BifrostModalValues = useInitialValues(
    isOnboarding,
    LLMProviderName.BIFROST,
    existingLlmProvider
  ) as BifrostModalValues;

  // useInitialValues drops custom_config, so seed it for submitProvider's
  // custom_config_changed diff, preserving any other stored entries.
  const initialMode =
    (existingLlmProvider?.custom_config?.[BIFROST_API_MODE_KEY] as
      | BifrostApiMode
      | undefined) ?? DEFAULT_API_MODE;
  initialValues.custom_config = {
    ...existingLlmProvider?.custom_config,
    [BIFROST_API_MODE_KEY]: initialMode,
  };

  const validationSchema = buildValidationSchema(t, isOnboarding, {
    apiBase: true,
  });

  return (
    <ModalWrapper
      providerName={LLMProviderName.BIFROST}
      llmProvider={existingLlmProvider}
      onClose={onClose}
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
          providerName: LLMProviderName.BIFROST,
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
      <BifrostModalInternals
        existingLlmProvider={existingLlmProvider}
        isOnboarding={isOnboarding}
      />
    </ModalWrapper>
  );
}
