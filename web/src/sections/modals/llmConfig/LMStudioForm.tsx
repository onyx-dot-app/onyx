"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSWRConfig } from "swr";
import { Formik, useFormikContext } from "formik";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import * as InputLayouts from "@/layouts/input-layouts";
import {
  LLMProviderFormProps,
  LLMProviderName,
  LLMProviderView,
  ModelConfiguration,
} from "@/interfaces/llm";
import {
  useTestingModelFromLLMProvider,
  useWellKnownLLMProvider,
} from "@/hooks/useLLMProviders";
import {
  buildInitialValues,
  buildValidationSchema,
  buildAvailableModelConfigurations,
  BaseLLMFormValues,
} from "@/sections/modals/llmConfig/utils";
import {
  submitLLMProvider,
  submitOnboardingProvider,
} from "@/sections/modals/llmConfig/svc";
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

const DEFAULT_API_BASE = "http://localhost:1234";

interface LMStudioFormValues extends BaseLLMFormValues {
  api_base: string;
  custom_config: {
    LM_STUDIO_API_KEY?: string;
  };
}

interface LMStudioFormInternalsProps {
  existingLlmProvider: LLMProviderView | undefined;
  fetchedModels: ModelConfiguration[];
  setFetchedModels: (models: ModelConfiguration[]) => void;
  onClose: () => void;
  isOnboarding: boolean;
}

function LMStudioFormInternals({
  existingLlmProvider,
  fetchedModels,
  setFetchedModels,
  onClose,
  isOnboarding,
}: LMStudioFormInternalsProps) {
  const formikProps = useFormikContext<LMStudioFormValues>();
  const initialApiKey =
    (existingLlmProvider?.custom_config?.LM_STUDIO_API_KEY as string) ?? "";

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
          setFetchedModels([]);
          return;
        }
        setFetchedModels(data.models);
      });
    },
    [existingLlmProvider?.name, initialApiKey, setFetchedModels]
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
      setFetchedModels([]);
    }
  }, [apiBase, apiKey, debouncedFetchModels, setFetchedModels]);

  const currentModels =
    fetchedModels.length > 0
      ? fetchedModels
      : existingLlmProvider?.model_configurations || [];

  return (
    <ModalWrapper
      providerName={LLMProviderName.LM_STUDIO}
      llmProvider={existingLlmProvider}
      onClose={onClose}
    >
      <APIBaseField
        subDescription="The base URL for your LM Studio server."
        placeholder="Your LM Studio API base URL"
      />

      <APIKeyField
        name="custom_config.LM_STUDIO_API_KEY"
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
      <ModelSelectionField
        modelConfigurations={currentModels}
        recommendedDefaultModel={null}
        shouldShowAutoUpdateToggle={false}
      />

      {!isOnboarding && (
        <>
          <InputLayouts.FieldSeparator />
          <ModelAccessField />
        </>
      )}
    </ModalWrapper>
  );
}

export default function LMStudioForm({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  onOpenChange,
  defaultModelName,
  onboardingState,
  onboardingActions,
  llmDescriptor,
}: LLMProviderFormProps) {
  const [fetchedModels, setFetchedModels] = useState<ModelConfiguration[]>([]);
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();
  const { wellKnownLLMProvider } = useWellKnownLLMProvider(
    LLMProviderName.LM_STUDIO
  );

  const onClose = () => onOpenChange?.(false);

  const modelConfigurations = buildAvailableModelConfigurations(
    existingLlmProvider,
    wellKnownLLMProvider ?? llmDescriptor
  );

  const initialValues: LMStudioFormValues = {
    ...buildInitialValues(LLMProviderName.LM_STUDIO, existingLlmProvider),
    api_base: existingLlmProvider?.api_base ?? DEFAULT_API_BASE,
    test_model_name: useTestingModelFromLLMProvider(
      LLMProviderName.LM_STUDIO,
      existingLlmProvider
    ),
    custom_config: {
      LM_STUDIO_API_KEY:
        (existingLlmProvider?.custom_config?.LM_STUDIO_API_KEY as string) ?? "",
    },
  } as LMStudioFormValues;

  const validationSchema = buildValidationSchema(isOnboarding, {
    apiBase: true,
  });

  return (
    <Formik
      initialValues={initialValues}
      validationSchema={validationSchema}
      validateOnMount
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

        if (isOnboarding && onboardingState && onboardingActions) {
          const modelConfigsToUse =
            fetchedModels.length > 0 ? fetchedModels : [];

          await submitOnboardingProvider({
            providerName: LLMProviderName.LM_STUDIO,
            payload: {
              ...submitValues,
              model_configurations: modelConfigsToUse,
            },
            onboardingState,
            onboardingActions,
            isCustomProvider: false,
            onClose,
            setIsSubmitting: setSubmitting,
          });
        } else {
          await submitLLMProvider({
            providerName: LLMProviderName.LM_STUDIO,
            values: submitValues,
            initialValues,
            modelConfigurations:
              fetchedModels.length > 0 ? fetchedModels : modelConfigurations,
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
      {() => (
        <LMStudioFormInternals
          existingLlmProvider={existingLlmProvider}
          fetchedModels={fetchedModels}
          setFetchedModels={setFetchedModels}
          onClose={onClose}
          isOnboarding={isOnboarding}
        />
      )}
    </Formik>
  );
}
