"use client";

import { InputSingleSelectField } from "@opal/form";
import { InputDivider, InputPadder, InputVertical, toast } from "@opal/layouts";
import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import {
  LLMProviderFormProps,
  LLMProviderName,
} from "@/lib/languageModels/types";
import {
  BaseLLMFormValues,
  buildValidationSchema,
  useInitialValues,
} from "@/sections/modals/languageModels/utils";
import { submitProvider } from "@/sections/modals/languageModels/svc";
import { LLMProviderConfiguredSource } from "@/lib/analytics/utils";
import {
  APIKeyField,
  DisplayNameField,
  ModalWrapper,
  ModelAccessField,
  ModelSelectionField,
} from "@/sections/modals/languageModels/shared";
import { refreshLlmProviderCaches } from "@/lib/languageModels/cache";

export const MINIMAX_ENDPOINT_OPTIONS = [
  {
    value: "https://api.minimax.io/anthropic",
  },
  {
    value: "https://api.minimax.io/v1",
  },
  {
    value: "https://api.minimaxi.com/anthropic",
  },
  {
    value: "https://api.minimaxi.com/v1",
  },
] as const;

interface MiniMaxModalValues extends BaseLLMFormValues {
  api_key: string;
  api_base: string;
}

function MiniMaxEndpointField() {
  const t = useTranslations("admin.languageModels.modals");
  const tInputSelect = useTranslations("common.inputSelect");

  return (
    <InputPadder>
      <InputVertical withLabel="api_base" title={t("setup.apiBaseField.title")}>
        <InputSingleSelectField
          name="api_base"
          placeholder={tInputSelect("placeholder.fallback")}
          options={MINIMAX_ENDPOINT_OPTIONS.map(({ value }) => ({
            value,
            title: value,
          }))}
        />
      </InputVertical>
    </InputPadder>
  );
}

export default function MiniMaxModal({
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

  const baseInitialValues = useInitialValues(
    isOnboarding,
    LLMProviderName.MINIMAX,
    existingLlmProvider
  );
  const initialValues: MiniMaxModalValues = {
    ...baseInitialValues,
    api_key: baseInitialValues.api_key ?? "",
    api_base: baseInitialValues.api_base ?? MINIMAX_ENDPOINT_OPTIONS[0].value,
  };

  const validationSchema = buildValidationSchema(t, isOnboarding, {
    apiKey: true,
    apiBase: true,
  });

  return (
    <ModalWrapper
      providerName={LLMProviderName.MINIMAX}
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
          providerName: LLMProviderName.MINIMAX,
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
      <MiniMaxEndpointField />

      <APIKeyField providerName="MiniMax" />

      {!isOnboarding && (
        <>
          <InputDivider />
          <DisplayNameField />
        </>
      )}

      <InputDivider />
      <ModelSelectionField shouldShowAutoUpdateToggle={true} />

      {!isOnboarding && (
        <>
          <InputDivider />
          <ModelAccessField />
        </>
      )}
    </ModalWrapper>
  );
}
