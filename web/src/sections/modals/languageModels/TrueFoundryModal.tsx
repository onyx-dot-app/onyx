"use client";

import { useTranslations } from "next-intl";
import { markdown } from "@opal/utils";
import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import { InputDivider, toast } from "@opal/layouts";
import {
  LLMProviderFormProps,
  LLMProviderName,
  LLMProviderView,
} from "@/lib/languageModels/types";
import { fetchTrueFoundryModels } from "@/lib/languageModels/svc";
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

const DEFAULT_API_BASE = "https://gateway.truefoundry.ai";

interface TrueFoundryModalValues extends BaseLLMFormValues {
  api_key: string;
  api_base: string;
}

interface TrueFoundryModalInternalsProps {
  existingLlmProvider: LLMProviderView | undefined;
  isOnboarding: boolean;
}

function TrueFoundryModalInternals({
  existingLlmProvider,
  isOnboarding,
}: TrueFoundryModalInternalsProps) {
  const t = useTranslations("admin.languageModels.modals");
  const formikProps = useFormikContext<TrueFoundryModalValues>();

  // The listing is scoped to the token, so both fields are needed to fetch.
  const isFetchDisabled =
    !formikProps.values.api_base || !formikProps.values.api_key;

  const handleFetchModels = async () => {
    const { models: fetched, error } = await fetchTrueFoundryModels({
      api_base: formikProps.values.api_base,
      api_key: formikProps.values.api_key,
      provider_id: existingLlmProvider?.id ?? undefined,
    });
    if (error) {
      throw new Error(error);
    }
    formikProps.setValues(withFetchedModels(fetched));
  };

  return (
    <>
      <APIBaseField
        subDescription={t("truefoundry.apiBaseField.description")}
        placeholder={t("truefoundry.apiBaseField.placeholder")}
      />

      <APIKeyField
        subDescription={markdown(t("truefoundry.apiKeyField.description"))}
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

export default function TrueFoundryModal({
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

  const initialValues: TrueFoundryModalValues = {
    ...useInitialValues(
      isOnboarding,
      LLMProviderName.TRUEFOUNDRY,
      existingLlmProvider
    ),
    api_base: existingLlmProvider?.api_base ?? DEFAULT_API_BASE,
  } as TrueFoundryModalValues;

  const validationSchema = buildValidationSchema(t, isOnboarding, {
    apiKey: true,
    apiBase: true,
  });

  return (
    <ModalWrapper
      providerName={LLMProviderName.TRUEFOUNDRY}
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
          providerName: LLMProviderName.TRUEFOUNDRY,
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
      <TrueFoundryModalInternals
        existingLlmProvider={existingLlmProvider}
        isOnboarding={isOnboarding}
      />
    </ModalWrapper>
  );
}
