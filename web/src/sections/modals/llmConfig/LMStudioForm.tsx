"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSWRConfig } from "swr";
import { Formik, FormikProps } from "formik";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import * as InputLayouts from "@/layouts/input-layouts";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import {
  LLMProviderFormProps,
  LLMProviderName,
  LLMProviderView,
  ModelConfiguration,
} from "@/interfaces/llm";
import * as Yup from "yup";
import { useWellKnownLLMProvider } from "@/hooks/useLLMProviders";
import {
  buildDefaultInitialValues,
  buildDefaultValidationSchema,
  buildAvailableModelConfigurations,
  buildOnboardingInitialValues,
  BaseLLMFormValues,
} from "@/sections/modals/llmConfig/utils";
import {
  submitLLMProvider,
  submitOnboardingProvider,
} from "@/sections/modals/llmConfig/svc";
import {
  ModelsField,
  DisplayNameField,
  ModelsAccessField,
  FieldSeparator,
  FieldWrapper,
  SingleDefaultModelField,
  LLMConfigurationModalWrapper,
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
  formikProps: FormikProps<LMStudioFormValues>;
  existingLlmProvider: LLMProviderView | undefined;
  fetchedModels: ModelConfiguration[];
  setFetchedModels: (models: ModelConfiguration[]) => void;
  isTesting: boolean;
  onClose: () => void;
  isOnboarding: boolean;
}

function LMStudioFormInternals({
  formikProps,
  existingLlmProvider,
  fetchedModels,
  setFetchedModels,
  isTesting,
  onClose,
  isOnboarding,
}: LMStudioFormInternalsProps) {
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
    <LLMConfigurationModalWrapper
      providerEndpoint={LLMProviderName.LM_STUDIO}
      existingProviderName={existingLlmProvider?.name}
      onClose={onClose}
      isFormValid={formikProps.isValid}
      isDirty={formikProps.dirty}
      isTesting={isTesting}
      isSubmitting={formikProps.isSubmitting}
    >
      <FieldWrapper>
        <InputLayouts.Vertical
          name="api_base"
          title="API Base URL"
          subDescription="The base URL for your LM Studio server."
        >
          <InputTypeInField
            name="api_base"
            placeholder="Your LM Studio API base URL"
          />
        </InputLayouts.Vertical>
      </FieldWrapper>

      <FieldWrapper>
        <InputLayouts.Vertical
          name="custom_config.LM_STUDIO_API_KEY"
          title="API Key"
          subDescription="Optional API key if your LM Studio server requires authentication."
          optional
        >
          <PasswordInputTypeInField
            name="custom_config.LM_STUDIO_API_KEY"
            placeholder="API Key"
          />
        </InputLayouts.Vertical>
      </FieldWrapper>

      {!isOnboarding && (
        <>
          <FieldSeparator />
          <DisplayNameField disabled={!!existingLlmProvider} />
        </>
      )}

      <FieldSeparator />

      {isOnboarding ? (
        <SingleDefaultModelField placeholder="E.g. llama3.1" />
      ) : (
        <ModelsField
          modelConfigurations={currentModels}
          formikProps={formikProps}
          recommendedDefaultModel={null}
          shouldShowAutoUpdateToggle={false}
        />
      )}

      {!isOnboarding && (
        <>
          <FieldSeparator />
          <ModelsAccessField formikProps={formikProps} />
        </>
      )}
    </LLMConfigurationModalWrapper>
  );
}

export default function LMStudioForm({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  open,
  onOpenChange,
  defaultModelName,
  onboardingState,
  onboardingActions,
  llmDescriptor,
}: LLMProviderFormProps) {
  const [fetchedModels, setFetchedModels] = useState<ModelConfiguration[]>([]);
  const [isTesting, setIsTesting] = useState(false);
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();
  const { wellKnownLLMProvider } = useWellKnownLLMProvider(
    LLMProviderName.LM_STUDIO
  );

  if (open === false) return null;

  const onClose = () => onOpenChange?.(false);

  const modelConfigurations = buildAvailableModelConfigurations(
    existingLlmProvider,
    wellKnownLLMProvider ?? llmDescriptor
  );

  const initialValues: LMStudioFormValues = isOnboarding
    ? ({
        ...buildOnboardingInitialValues(),
        name: LLMProviderName.LM_STUDIO,
        provider: LLMProviderName.LM_STUDIO,
        api_base: DEFAULT_API_BASE,
        default_model_name: "",
        custom_config: {
          LM_STUDIO_API_KEY: "",
        },
      } as LMStudioFormValues)
    : {
        ...buildDefaultInitialValues(
          existingLlmProvider,
          modelConfigurations,
          defaultModelName
        ),
        api_base: existingLlmProvider?.api_base ?? DEFAULT_API_BASE,
        custom_config: {
          LM_STUDIO_API_KEY:
            (existingLlmProvider?.custom_config?.LM_STUDIO_API_KEY as string) ??
            "",
        },
      };

  const validationSchema = isOnboarding
    ? Yup.object().shape({
        api_base: Yup.string().required("API Base URL is required"),
        default_model_name: Yup.string().required("Model name is required"),
      })
    : buildDefaultValidationSchema().shape({
        api_base: Yup.string().required("API Base URL is required"),
      });

  return (
    <Formik
      initialValues={initialValues}
      validationSchema={validationSchema}
      validateOnMount={true}
      onSubmit={async (values, { setSubmitting }) => {
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
            setIsTesting,
            mutate,
            onClose,
            setSubmitting,
          });
        }
      }}
    >
      {(formikProps) => (
        <LMStudioFormInternals
          formikProps={formikProps}
          existingLlmProvider={existingLlmProvider}
          fetchedModels={fetchedModels}
          setFetchedModels={setFetchedModels}
          isTesting={isTesting}
          onClose={onClose}
          isOnboarding={isOnboarding}
        />
      )}
    </Formik>
  );
}
