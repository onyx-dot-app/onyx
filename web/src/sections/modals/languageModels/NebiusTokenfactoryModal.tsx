"use client";

import { useEffect, useRef } from "react";
import { markdown } from "@opal/utils";
import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import { InputDivider } from "@opal/layouts";
import {
  LLMProviderFormProps,
  LLMProviderName,
  LLMProviderView,
} from "@/lib/languageModels/types";
import { fetchNebiusTokenfactoryModels } from "@/lib/languageModels/svc";
import {
  useInitialValues,
  buildValidationSchema,
  BaseLLMFormValues,
  mergeFetchedModelConfigurations,
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
import { toast } from "@/hooks/useToast";
import { refreshLlmProviderCaches } from "@/lib/languageModels/cache";

const DEFAULT_API_BASE = "https://api.tokenfactory.nebius.com/v1";

interface NebiusTokenfactoryModalValues extends BaseLLMFormValues {
  api_key: string;
  api_base: string;
}

interface NebiusTokenfactoryModalInternalsProps {
  existingLlmProvider: LLMProviderView | undefined;
  isOnboarding: boolean;
}

function NebiusTokenfactoryModalInternals({
  existingLlmProvider,
  isOnboarding,
}: NebiusTokenfactoryModalInternalsProps) {
  const formikProps = useFormikContext<NebiusTokenfactoryModalValues>();
  const { setFieldValue } = formikProps;

  const isFetchDisabled = !formikProps.values.api_base;

  const handleFetchModels = async () => {
    const { models, error } = await fetchNebiusTokenfactoryModels({
      api_base: formikProps.values.api_base,
      api_key: formikProps.values.api_key || undefined,
      provider_id: existingLlmProvider?.id ?? undefined,
    });
    if (error) {
      throw new Error(error);
    }
    formikProps.setFieldValue(
      "model_configurations",
      mergeFetchedModelConfigurations(
        models,
        formikProps.values.model_configurations
      )
    );
  };

  // When editing a saved provider, the models load from the DB without the
  // per-model metadata (context/flag/quantization/features) — so refetch once
  // on open to make the picker match the "add" view. Best-effort: ignore
  // errors so the modal still works if the provider is unreachable.
  const autoRefetched = useRef(false);
  useEffect(() => {
    if (autoRefetched.current || !existingLlmProvider?.id) return;
    if (!formikProps.values.api_base) return;
    autoRefetched.current = true;
    fetchNebiusTokenfactoryModels({
      api_base: formikProps.values.api_base,
      api_key: formikProps.values.api_key || undefined,
      provider_id: existingLlmProvider.id,
    })
      .then(({ models }) => {
        if (models.length > 0) {
          setFieldValue(
            "model_configurations",
            mergeFetchedModelConfigurations(
              models,
              formikProps.values.model_configurations
            )
          );
        }
      })
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      <APIBaseField
        subDescription="Nebius TokenFactory endpoint URL (including API version)."
        placeholder={DEFAULT_API_BASE}
      />

      <APIKeyField
        subDescription={markdown(
          "Paste your API key from [Nebius TokenFactory](https://tokenfactory.nebius.com/) to load the available models."
        )}
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

export default function NebiusTokenfactoryModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  onOpenChange,
  onSuccess,
}: LLMProviderFormProps) {
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();

  const onClose = () => onOpenChange?.(false);

  const initialValues: NebiusTokenfactoryModalValues = useInitialValues(
    isOnboarding,
    LLMProviderName.NEBIUS_TOKENFACTORY,
    existingLlmProvider
  ) as NebiusTokenfactoryModalValues;

  // Nebius TokenFactory always uses the same base; default it whenever it's
  // missing (new provider, or an edit where the base wasn't persisted) so the
  // model refetch always has a valid endpoint.
  if (!initialValues.api_base) {
    initialValues.api_base = DEFAULT_API_BASE;
  }

  const validationSchema = buildValidationSchema(isOnboarding, {
    apiBase: true,
    apiKey: true,
  });

  return (
    <ModalWrapper
      providerName={LLMProviderName.NEBIUS_TOKENFACTORY}
      llmProvider={existingLlmProvider}
      onClose={onClose}
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={async (values, { setSubmitting, setStatus }) => {
        await submitProvider({
          analyticsSource: isOnboarding
            ? LLMProviderConfiguredSource.CHAT_ONBOARDING
            : LLMProviderConfiguredSource.ADMIN_PAGE,
          providerName: LLMProviderName.NEBIUS_TOKENFACTORY,
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
                  ? "Provider updated successfully!"
                  : "Provider enabled successfully!"
              );
            }
          },
        });
      }}
    >
      <NebiusTokenfactoryModalInternals
        existingLlmProvider={existingLlmProvider}
        isOnboarding={isOnboarding}
      />
    </ModalWrapper>
  );
}
