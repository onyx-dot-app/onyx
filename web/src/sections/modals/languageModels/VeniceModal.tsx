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
import { fetchVeniceModels } from "@/lib/languageModels/svc";
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

const DEFAULT_API_BASE = "https://api.venice.ai/api/v1";

interface VeniceModalValues extends BaseLLMFormValues {
  api_key: string;
  api_base: string;
}

interface VeniceModalInternalsProps {
  existingLlmProvider: LLMProviderView | undefined;
  isOnboarding: boolean;
}

function VeniceModalInternals({
  existingLlmProvider,
  isOnboarding,
}: VeniceModalInternalsProps) {
  const t = useTranslations("admin.languageModels.modals");
  const formikProps = useFormikContext<VeniceModalValues>();

  const isFetchDisabled = !formikProps.values.api_base;

  const handleFetchModels = async () => {
    const { models, error } = await fetchVeniceModels({
      api_base: formikProps.values.api_base,
      api_key: formikProps.values.api_key || undefined,
      provider_id: existingLlmProvider?.id ?? undefined,
    });
    if (error) {
      throw new Error(error);
    }
    formikProps.setValues(withFetchedModels(models));
  };

  // Saved providers load from the DB without the per-model context window and
  // capability flags, so refetch once on open to match the "add" view.
  // Best-effort: ignore errors so the modal still works when Venice is
  // unreachable.
  const autoRefetched = useRef(false);
  useEffect(() => {
    if (autoRefetched.current || !existingLlmProvider?.id) return;
    if (!formikProps.values.api_base) return;
    autoRefetched.current = true;
    fetchVeniceModels({
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      <APIKeyField
        subDescription={markdown(t("venice.apiKeyField.description"))}
      />

      <InputDivider />
      <APIBaseField
        subDescription={t("venice.apiBaseField.description")}
        placeholder={DEFAULT_API_BASE}
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

export default function VeniceModal({
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

  const initialValues: VeniceModalValues = useInitialValues(
    isOnboarding,
    LLMProviderName.VENICE,
    existingLlmProvider
  ) as VeniceModalValues;

  // Venice is a hosted service on one base. Default it whenever it's missing
  // so the model fetch always has an endpoint to call.
  if (!initialValues.api_base) {
    initialValues.api_base = DEFAULT_API_BASE;
  }

  const validationSchema = buildValidationSchema(t, isOnboarding, {
    apiBase: true,
    apiKey: true,
  });

  return (
    <ModalWrapper
      providerName={LLMProviderName.VENICE}
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
          providerName: LLMProviderName.VENICE,
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
      <VeniceModalInternals
        existingLlmProvider={existingLlmProvider}
        isOnboarding={isOnboarding}
      />
    </ModalWrapper>
  );
}
