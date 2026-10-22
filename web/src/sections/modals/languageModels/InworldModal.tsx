"use client";

import { useTranslations } from "next-intl";
import { useEffect, useRef } from "react";
import { markdown } from "@opal/utils";
import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import { InputDivider, toast } from "@opal/layouts";
import {
  LLMProviderFormProps,
  LLMProviderName,
  LLMProviderView,
} from "@/lib/languageModels/types";
import { fetchInworldModels } from "@/lib/languageModels/svc";
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

const DEFAULT_API_BASE = "https://api.inworld.ai/v1";

interface InworldModalValues extends BaseLLMFormValues {
  api_key: string;
  api_base: string;
}

interface InworldModalInternalsProps {
  existingLlmProvider: LLMProviderView | undefined;
  isOnboarding: boolean;
}

function InworldModalInternals({
  existingLlmProvider,
  isOnboarding,
}: InworldModalInternalsProps) {
  const t = useTranslations("admin.languageModels.modals");
  const formikProps = useFormikContext<InworldModalValues>();

  const isFetchDisabled =
    !formikProps.values.api_base || !formikProps.values.api_key;

  const handleFetchModels = async (signal: AbortSignal) => {
    const { models, error } = await fetchInworldModels({
      api_base: formikProps.values.api_base,
      api_key: formikProps.values.api_key || undefined,
      provider_id: existingLlmProvider?.id ?? undefined,
      signal,
    });
    if (signal.aborted) return;
    if (error) {
      throw new Error(error);
    }
    formikProps.setValues(withFetchedModels(models));
  };

  // Refresh capabilities on edit without changing saved selections.
  const autoRefetched = useRef(false);
  useEffect(() => {
    if (autoRefetched.current || !existingLlmProvider?.id) return;
    if (!formikProps.values.api_base) return;
    autoRefetched.current = true;
    fetchInworldModels({
      api_base: formikProps.values.api_base,
      api_key: formikProps.values.api_key || undefined,
      provider_id: existingLlmProvider.id,
    })
      .then(({ models }) => {
        if (models.length > 0) {
          formikProps.setValues(withFetchedModels(models));
        }
      })
      .catch(() => undefined);
  }, [
    existingLlmProvider?.id,
    formikProps.values.api_base,
    formikProps.values.api_key,
    formikProps.setValues,
  ]);

  return (
    <>
      <APIBaseField
        subDescription={t("inworld.apiBaseField.description")}
        placeholder={DEFAULT_API_BASE}
      />

      <APIKeyField
        subDescription={markdown(t("inworld.apiKeyField.description"))}
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

export default function InworldModal({
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

  const baseValues = useInitialValues(
    isOnboarding,
    LLMProviderName.INWORLD,
    existingLlmProvider
  );
  const initialValues: InworldModalValues = {
    ...baseValues,
    api_key: baseValues.api_key ?? "",
    api_base: baseValues.api_base || DEFAULT_API_BASE,
  };

  const validationSchema = buildValidationSchema(t, isOnboarding, {
    apiBase: true,
    apiKey: true,
  });

  return (
    <ModalWrapper
      providerName={LLMProviderName.INWORLD}
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
          providerName: LLMProviderName.INWORLD,
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
      <InworldModalInternals
        existingLlmProvider={existingLlmProvider}
        isOnboarding={isOnboarding}
      />
    </ModalWrapper>
  );
}
