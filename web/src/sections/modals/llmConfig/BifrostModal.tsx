"use client";

import { useEffect } from "react";
import { markdown } from "@opal/utils";
import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import * as InputLayouts from "@/layouts/input-layouts";
import {
  LLMProviderFormProps,
  LLMProviderName,
  LLMProviderView,
} from "@/interfaces/llm";
import { fetchBifrostModels } from "@/app/admin/configuration/llm/utils";
import {
  useInitialValues,
  buildValidationSchema,
  BaseLLMFormValues,
} from "@/sections/modals/llmConfig/utils";
import {
  submitLLMProvider,
  submitOnboardingProvider,
} from "@/sections/modals/llmConfig/svc";
import {
  APIBaseField,
  APIKeyField,
  ModelSelectionField,
  DisplayNameField,
  ModelAccessField,
  ModalWrapper,
} from "@/sections/modals/llmConfig/shared";
import { toast } from "@/hooks/useToast";

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
  const formikProps = useFormikContext<BifrostModalValues>();

  const isFetchDisabled = !formikProps.values.api_base;

  const handleFetchModels = async () => {
    const { models, error } = await fetchBifrostModels({
      api_base: formikProps.values.api_base,
      api_key: formikProps.values.api_key || undefined,
      provider_name: existingLlmProvider?.name,
    });
    if (error) {
      throw new Error(error);
    }
    formikProps.setFieldValue("model_configurations", models);
  };

  // Auto-fetch models on initial load when editing an existing provider
  useEffect(() => {
    if (existingLlmProvider && !isFetchDisabled) {
      handleFetchModels().catch((err) => {
        console.error("Failed to fetch Bifrost models:", err);
        toast.error(
          err instanceof Error ? err.message : "Failed to fetch models"
        );
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      <APIBaseField
        subDescription="Paste your Bifrost gateway endpoint URL (including API version)."
        placeholder="https://your-bifrost-gateway.com/v1"
      />

      <APIKeyField
        optional
        subDescription={markdown(
          "Paste your API key from [Bifrost](https://docs.getbifrost.ai/overview) to access your models."
        )}
      />

      {!isOnboarding && (
        <>
          <InputLayouts.FieldSeparator />
          <DisplayNameField disabled={!!existingLlmProvider} />
        </>
      )}

      <InputLayouts.FieldSeparator />
      <ModelSelectionField
        shouldShowAutoUpdateToggle={false}
        onRefetch={isFetchDisabled ? undefined : handleFetchModels}
      />

      {!isOnboarding && (
        <>
          <InputLayouts.FieldSeparator />
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
  defaultModelName,
  onboardingState,
  onboardingActions,
  llmDescriptor,
}: LLMProviderFormProps) {
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();

  const onClose = () => onOpenChange?.(false);

  const initialValues: BifrostModalValues = useInitialValues(
    isOnboarding,
    LLMProviderName.BIFROST,
    existingLlmProvider
  ) as BifrostModalValues;

  const validationSchema = buildValidationSchema(isOnboarding, {
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
        if (isOnboarding && onboardingState && onboardingActions) {
          await submitOnboardingProvider({
            providerName: LLMProviderName.BIFROST,
            payload: {
              ...values,
            },
            onboardingState,
            onboardingActions,
            isCustomProvider: false,
            onClose,
            setIsSubmitting: setSubmitting,
          });
        } else {
          await submitLLMProvider({
            providerName: LLMProviderName.BIFROST,
            values,
            initialValues,
            existingLlmProvider,
            shouldMarkAsDefault,
            setStatus,
            mutate,
            onClose,
            setSubmitting,
          });
        }
      }}
    >
      <BifrostModalInternals
        existingLlmProvider={existingLlmProvider}
        isOnboarding={isOnboarding}
      />
    </ModalWrapper>
  );
}
