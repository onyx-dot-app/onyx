"use client";

import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import { InputDivider, toast } from "@opal/layouts";
import {
  LLMProviderFormProps,
  LLMProviderName,
  LLMProviderView,
} from "@/lib/languageModels/types";
import { fetchVercelAIGatewayModels } from "@/lib/languageModels/svc";
import {
  useInitialValues,
  buildValidationSchema,
  BaseLLMFormValues,
  withFetchedModels,
} from "@/sections/modals/languageModels/utils";
import { submitProvider } from "@/sections/modals/languageModels/svc";
import { LLMProviderConfiguredSource } from "@/lib/analytics/utils";
import {
  APIKeyField,
  APIBaseField,
  ModelSelectionField,
  DisplayNameField,
  ModelAccessField,
  ModalWrapper,
} from "@/sections/modals/languageModels/shared";
import { refreshLlmProviderCaches } from "@/lib/languageModels/cache";

const DEFAULT_API_BASE = "https://ai-gateway.vercel.sh/v1";

interface VercelAIGatewayModalValues extends BaseLLMFormValues {
  api_key: string;
  api_base: string;
}

interface VercelAIGatewayModalInternalsProps {
  existingLlmProvider: LLMProviderView | undefined;
  isOnboarding: boolean;
}

function VercelAIGatewayModalInternals({
  existingLlmProvider,
  isOnboarding,
}: VercelAIGatewayModalInternalsProps) {
  const t = useTranslations("admin.languageModels.modals");
  const formikProps = useFormikContext<VercelAIGatewayModalValues>();

  // The catalog is public, so models list before a key is entered.
  const isFetchDisabled = !formikProps.values.api_base;

  const handleFetchModels = async () => {
    const { models: fetched, error } = await fetchVercelAIGatewayModels({
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
        subDescription={t("vercelAiGateway.apiBaseField.description")}
        placeholder={t("vercelAiGateway.apiBaseField.placeholder")}
      />

      <APIKeyField providerName="Vercel AI Gateway" />

      {!isOnboarding && (
        <>
          <InputDivider />
          <DisplayNameField />
        </>
      )}

      <InputDivider />
      <ModelSelectionField
        shouldShowAutoUpdateToggle={true}
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

export default function VercelAIGatewayModal({
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

  const initialValues: VercelAIGatewayModalValues = {
    ...useInitialValues(
      isOnboarding,
      LLMProviderName.VERCEL_AI_GATEWAY,
      existingLlmProvider
    ),
    api_base: existingLlmProvider?.api_base ?? DEFAULT_API_BASE,
  } as VercelAIGatewayModalValues;

  const validationSchema = buildValidationSchema(t, isOnboarding, {
    apiKey: true,
    apiBase: true,
  });

  return (
    <ModalWrapper
      providerName={LLMProviderName.VERCEL_AI_GATEWAY}
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
          providerName: LLMProviderName.VERCEL_AI_GATEWAY,
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
      <VercelAIGatewayModalInternals
        existingLlmProvider={existingLlmProvider}
        isOnboarding={isOnboarding}
      />
    </ModalWrapper>
  );
}
