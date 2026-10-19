"use client";

import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import { Text } from "@opal/components";
import { InputDivider, toast } from "@opal/layouts";
import {
  LLMProviderFormProps,
  LLMProviderName,
} from "@/lib/languageModels/types";
import { refreshLlmProviderCaches } from "@/lib/languageModels/cache";
import {
  buildValidationSchema,
  useInitialValues,
} from "@/sections/modals/languageModels/utils";
import { submitProvider } from "@/sections/modals/languageModels/svc";
import {
  APIKeyField,
  DisplayNameField,
  ModalWrapper,
} from "@/sections/modals/languageModels/shared";

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
    model_configurations: [],
    test_model_name: "jev-latest",
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
    </ModalWrapper>
  );
}
