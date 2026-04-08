"use client";

import { useCallback, useEffect, useMemo } from "react";
import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import * as InputLayouts from "@/layouts/input-layouts";
import {
  LLMProviderFormProps,
  LLMProviderName,
  LLMProviderView,
} from "@/interfaces/llm";
import {
  useInitialValues,
  buildValidationSchema,
  BaseLLMFormValues as BaseLLMModalValues,
} from "@/sections/modals/llmConfig/utils";
import { submitProvider } from "@/sections/modals/llmConfig/svc";
import { LLMProviderConfiguredSource } from "@/lib/analytics";
import {
  APIKeyField,
  APIBaseField,
  ModelSelectionField,
  DisplayNameField,
  ModelAccessField,
  ModalWrapper,
} from "@/sections/modals/llmConfig/shared";
import { fetchModels } from "@/app/admin/configuration/llm/utils";
import debounce from "lodash/debounce";
import { toast } from "@/hooks/useToast";
import { refreshLlmProviderCaches } from "@/lib/llmConfig/cache";

const DEFAULT_API_BASE = "http://localhost:1234";

interface LMStudioModalValues extends BaseLLMModalValues {
  api_base: string;
  custom_config: {
    LM_STUDIO_API_KEY?: string;
  };
}

interface LMStudioModalInternalsProps {
  existingLlmProvider: LLMProviderView | undefined;
  isOnboarding: boolean;
}

function LMStudioModalInternals({
  existingLlmProvider,
  isOnboarding,
}: LMStudioModalInternalsProps) {
  const formikProps = useFormikContext<LMStudioModalValues>();
  const initialApiKey = existingLlmProvider?.custom_config?.LM_STUDIO_API_KEY;

  const doFetchModels = useCallback(
    (apiBase: string, apiKey: string | undefined, signal: AbortSignal) => {
      fetchModels(
        LLMProviderName.LM_STUDIO,
        {
          api_base: apiBase,
          custom_config: apiKey ? { LM_STUDIO_API_KEY: apiKey } : {},
          api_key_changed: apiKey !== initialApiKey,
          name: existingLlmProvider?.name,
        },
        signal
      ).then((data) => {
        if (signal.aborted) return;
        if (data.error) {
          toast.error(data.error);
          formikProps.setFieldValue("model_configurations", []);
          return;
        }
        formikProps.setFieldValue("model_configurations", data.models);
      });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [existingLlmProvider?.name, initialApiKey]
  );

  const debouncedFetchModels = useMemo(
    () => debounce(doFetchModels, 500),
    [doFetchModels]
  );

  const apiBase = formikProps.values.api_base;
  const apiKey = formikProps.values.custom_config?.LM_STUDIO_API_KEY;

  useEffect(() => {
    if (apiBase) {
      const controller = new AbortController();
      debouncedFetchModels(apiBase, apiKey, controller.signal);
      return () => {
        debouncedFetchModels.cancel();
        controller.abort();
      };
    } else {
      formikProps.setFieldValue("model_configurations", []);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBase, apiKey, debouncedFetchModels]);

  return (
    <>
      <APIBaseField
        subDescription="The base URL for your LM Studio server."
        placeholder="Your LM Studio API base URL"
      />

      <APIKeyField
        optional
        subDescription="Optional API key if your LM Studio server requires authentication."
      />

      {!isOnboarding && (
        <>
          <InputLayouts.FieldSeparator />
          <DisplayNameField disabled={!!existingLlmProvider} />
        </>
      )}

      <InputLayouts.FieldSeparator />
      <ModelSelectionField shouldShowAutoUpdateToggle={false} />

      {!isOnboarding && (
        <>
          <InputLayouts.FieldSeparator />
          <ModelAccessField />
        </>
      )}
    </>
  );
}

export default function LMStudioModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  onOpenChange,
  onSuccess,
}: LLMProviderFormProps) {
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();

  const onClose = () => onOpenChange?.(false);

  const initialValues: LMStudioModalValues = {
    ...useInitialValues(
      isOnboarding,
      LLMProviderName.LM_STUDIO,
      existingLlmProvider
    ),
    api_base: existingLlmProvider?.api_base ?? DEFAULT_API_BASE,
    custom_config: {
      LM_STUDIO_API_KEY: existingLlmProvider?.custom_config?.LM_STUDIO_API_KEY,
    },
  } as LMStudioModalValues;

  const validationSchema = buildValidationSchema(isOnboarding, {
    apiBase: true,
  });

  return (
    <ModalWrapper
      providerName={LLMProviderName.LM_STUDIO}
      llmProvider={existingLlmProvider}
      onClose={onClose}
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={async (values, { setSubmitting, setStatus }) => {
        const filteredCustomConfig = Object.fromEntries(
          Object.entries(values.custom_config || {}).filter(([, v]) => v !== "")
        );

        const submitValues = {
          ...values,
          custom_config:
            Object.keys(filteredCustomConfig).length > 0
              ? filteredCustomConfig
              : undefined,
        };

        await submitProvider({
          analyticsSource: isOnboarding
            ? LLMProviderConfiguredSource.CHAT_ONBOARDING
            : LLMProviderConfiguredSource.ADMIN_PAGE,
          providerName: LLMProviderName.LM_STUDIO,
          values: submitValues,
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
      <LMStudioModalInternals
        existingLlmProvider={existingLlmProvider}
        isOnboarding={isOnboarding}
      />
    </ModalWrapper>
  );
}
