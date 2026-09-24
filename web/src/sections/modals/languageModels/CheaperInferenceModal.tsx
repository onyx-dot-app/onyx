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
import { fetchCheaperInferenceModels } from "@/lib/languageModels/svc";
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

const DEFAULT_API_BASE = "https://api.cheaperinference.com/v1";

interface CheaperInferenceModalValues extends BaseLLMFormValues {
  api_key: string;
  api_base: string;
}

interface CheaperInferenceModalInternalsProps {
  existingLlmProvider: LLMProviderView | undefined;
  isOnboarding: boolean;
}

function CheaperInferenceModalInternals({
  existingLlmProvider,
  isOnboarding,
}: CheaperInferenceModalInternalsProps) {
  const t = useTranslations("admin.languageModels.modals");
  const formikProps = useFormikContext<CheaperInferenceModalValues>();

  const isFetchDisabled = !formikProps.values.api_base;

  const handleFetchModels = async () => {
    const { models, error } = await fetchCheaperInferenceModels({
      api_base: formikProps.values.api_base,
      api_key: formikProps.values.api_key || undefined,
      provider_id: existingLlmProvider?.id ?? undefined,
    });
    if (error) {
      throw new Error(error);
    }
    formikProps.setValues(withFetchedModels(models));
  };

  // Refetch once on open so an edit's picker matches the "add" view.
  // Best-effort: a failure leaves the stored picker in place so the modal still
  // works when the gateway is unreachable, but it is logged either way - the
  // service reports failures in `error` rather than by throwing.
  const autoRefetched = useRef(false);
  useEffect(() => {
    if (autoRefetched.current || !existingLlmProvider?.id) return;
    if (!formikProps.values.api_base) return;
    autoRefetched.current = true;
    fetchCheaperInferenceModels({
      api_base: formikProps.values.api_base,
      api_key: formikProps.values.api_key || undefined,
      provider_id: existingLlmProvider.id,
    })
      .then(({ models, error }) => {
        if (error) {
          console.warn(
            "Cheaper Inference model refresh failed; keeping the stored models",
            error
          );
          return;
        }
        if (models.length > 0) {
          formikProps.setValues(withFetchedModels(models));
        }
      })
      .catch((error) => {
        console.warn("Cheaper Inference model refresh threw", error);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      <APIBaseField
        subDescription={t("cheaperInference.apiBaseField.description")}
        placeholder={DEFAULT_API_BASE}
      />

      <APIKeyField
        subDescription={markdown(t("cheaperInference.apiKeyField.description"))}
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

export default function CheaperInferenceModal({
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

  // SAFETY: api_base is defaulted just below, and the validation schema blocks
  // submit until api_key is set, so both fields hold a string wherever the form
  // reads them.
  const initialValues: CheaperInferenceModalValues = useInitialValues(
    isOnboarding,
    LLMProviderName.CHEAPERINFERENCE,
    existingLlmProvider
  ) as CheaperInferenceModalValues;

  // The gateway is a hosted service on one base URL. Default it whenever it is
  // missing (new provider, or an edit where the base was not persisted) so the
  // model fetch always has a valid endpoint.
  if (!initialValues.api_base) {
    initialValues.api_base = DEFAULT_API_BASE;
  }

  const validationSchema = buildValidationSchema(t, isOnboarding, {
    apiBase: true,
    apiKey: true,
  });

  return (
    <ModalWrapper
      providerName={LLMProviderName.CHEAPERINFERENCE}
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
          providerName: LLMProviderName.CHEAPERINFERENCE,
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
      <CheaperInferenceModalInternals
        existingLlmProvider={existingLlmProvider}
        isOnboarding={isOnboarding}
      />
    </ModalWrapper>
  );
}
