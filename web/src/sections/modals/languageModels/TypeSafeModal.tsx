"use client";

import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import { Text } from "@opal/components";
import { InputDivider, toast } from "@opal/layouts";
import {
  LLMProviderFormProps,
  LLMProviderName,
  type LLMProviderView,
} from "@/lib/languageModels/types";
import { fetchTypeSafeModels } from "@/lib/languageModels/svc";
import { refreshLlmProviderCaches } from "@/lib/languageModels/cache";
import {
  buildValidationSchema,
  useInitialValues,
  withFetchedModels,
  type BaseLLMFormValues,
} from "@/sections/modals/languageModels/utils";
import { submitProvider } from "@/sections/modals/languageModels/svc";
import {
  APIKeyField,
  DisplayNameField,
  ModalWrapper,
  ModelSelectionField,
} from "@/sections/modals/languageModels/shared";

function TypeSafeModels({
  existingLlmProvider,
}: {
  existingLlmProvider?: LLMProviderView;
}) {
  const { values, setValues } = useFormikContext<BaseLLMFormValues>();
  async function fetchModels(signal: AbortSignal) {
    const models = await fetchTypeSafeModels({
      api_key:
        existingLlmProvider && values.api_key === existingLlmProvider.api_key
          ? undefined
          : values.api_key,
      provider_id: existingLlmProvider?.id,
      signal,
    });
    await setValues(withFetchedModels(models));
  }
  return (
    <ModelSelectionField
      shouldShowAutoUpdateToggle={false}
      testModelScope="all"
      onRefetch={
        values.api_key || existingLlmProvider ? fetchModels : undefined
      }
    />
  );
}

export default function TypeSafeModal({
  existingLlmProvider,
  onOpenChange,
  onSuccess,
  analyticsSource,
}: LLMProviderFormProps) {
  const t = useTranslations("admin.languageModels.modals");
  const { mutate } = useSWRConfig();
  const providerValues = useInitialValues(
    false,
    LLMProviderName.TYPESAFE,
    existingLlmProvider
  );
  const initialValues = {
    ...providerValues,
    is_auto_mode: false,
  };
  const onClose = () => onOpenChange?.(false);

  return (
    <ModalWrapper
      providerName={LLMProviderName.TYPESAFE}
      llmProvider={existingLlmProvider}
      onClose={onClose}
      initialValues={initialValues}
      validationSchema={buildValidationSchema(t, false, { apiKey: true })}
      onSubmit={async (values, { setSubmitting, setStatus }) => {
        await submitProvider({
          t,
          providerName: LLMProviderName.TYPESAFE,
          values,
          initialValues,
          existingLlmProvider,
          shouldMarkAsDefault: false,
          analyticsSource,
          setSubmitting,
          setStatus,
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
      <Text as="p">{t("typesafe.description")}</Text>
      <APIKeyField providerName="TypeSafe AI" />
      <InputDivider />
      <DisplayNameField />
      <InputDivider />
      <TypeSafeModels existingLlmProvider={existingLlmProvider} />
    </ModalWrapper>
  );
}
