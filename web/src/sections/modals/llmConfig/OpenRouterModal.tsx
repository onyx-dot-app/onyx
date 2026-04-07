"use client";

import { useState, useEffect } from "react";
import { useSWRConfig } from "swr";
import { Formik, useFormikContext } from "formik";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import * as InputLayouts from "@/layouts/input-layouts";
import {
  LLMProviderFormProps,
  LLMProviderView,
  ModelConfiguration,
} from "@/interfaces/llm";
import { fetchOpenRouterModels } from "@/app/admin/configuration/llm/utils";
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
  APIKeyField,
  ModelSelectionField,
  DisplayNameField,
  ModelAccessField,
  ModalWrapper,
} from "@/sections/modals/llmConfig/shared";
import { toast } from "@/hooks/useToast";

const OPENROUTER_PROVIDER_NAME = "openrouter";
const DEFAULT_API_BASE = "https://openrouter.ai/api/v1";
interface OpenRouterModalValues extends BaseLLMFormValues {
  api_key: string;
  api_base: string;
}

interface OpenRouterModalInternalsProps {
  existingLlmProvider: LLMProviderView | undefined;
  fetchedModels: ModelConfiguration[];
  setFetchedModels: (models: ModelConfiguration[]) => void;
  modelConfigurations: ModelConfiguration[];
  isTesting: boolean;
  onClose: () => void;
  isOnboarding: boolean;
}

function OpenRouterModalInternals({
  existingLlmProvider,
  fetchedModels,
  setFetchedModels,
  modelConfigurations,
  isTesting,
  onClose,
  isOnboarding,
}: OpenRouterModalInternalsProps) {
  const formikProps = useFormikContext<OpenRouterModalValues>();
  const currentModels =
    fetchedModels.length > 0
      ? fetchedModels
      : existingLlmProvider?.model_configurations || modelConfigurations;

  const isFetchDisabled =
    !formikProps.values.api_base || !formikProps.values.api_key;

  const handleFetchModels = async () => {
    const { models, error } = await fetchOpenRouterModels({
      api_base: formikProps.values.api_base,
      api_key: formikProps.values.api_key,
      provider_name: existingLlmProvider?.name,
    });
    if (error) {
      throw new Error(error);
    }
    setFetchedModels(models);
  };

  // Auto-fetch models on initial load when editing an existing provider
  useEffect(() => {
    if (existingLlmProvider && !isFetchDisabled) {
      handleFetchModels().catch((err) => {
        toast.error(
          err instanceof Error ? err.message : "Failed to fetch models"
        );
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <ModalWrapper
      providerEndpoint={OPENROUTER_PROVIDER_NAME}
      existingProviderName={existingLlmProvider?.name}
      onClose={onClose}
      isFormValid={formikProps.isValid}
      isDirty={formikProps.dirty}
      isTesting={isTesting}
      isSubmitting={formikProps.isSubmitting}
    >
      <InputLayouts.FieldPadder>
        <InputLayouts.Vertical
          name="api_base"
          title="API Base URL"
          subDescription="Paste your OpenRouter-compatible endpoint URL or use OpenRouter API directly."
        >
          <InputTypeInField
            name="api_base"
            placeholder="Your OpenRouter base URL"
          />
        </InputLayouts.Vertical>
      </InputLayouts.FieldPadder>

      <APIKeyField providerName="OpenRouter" />

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
        onRefetch={isFetchDisabled ? undefined : handleFetchModels}
      />

      {!isOnboarding && (
        <>
          <InputLayouts.FieldSeparator />
        </>
      )}
    </ModalWrapper>
  );
}

export default function OpenRouterModal({
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
  const [isTesting, setIsTesting] = useState(false);
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();
  const { wellKnownLLMProvider } = useWellKnownLLMProvider(
    OPENROUTER_PROVIDER_NAME
  );

  const onClose = () => onOpenChange?.(false);

  const modelConfigurations = buildAvailableModelConfigurations(
    existingLlmProvider,
    wellKnownLLMProvider ?? llmDescriptor
  );

  const initialValues: OpenRouterModalValues = isOnboarding
    ? ({
        ...buildOnboardingInitialValues(),
        name: OPENROUTER_PROVIDER_NAME,
        provider: OPENROUTER_PROVIDER_NAME,
        api_key: "",
        api_base: DEFAULT_API_BASE,
        default_model_name: "",
      } as OpenRouterModalValues)
    : {
        ...buildDefaultInitialValues(
          existingLlmProvider,
          modelConfigurations,
          defaultModelName
        ),
        api_key: existingLlmProvider?.api_key ?? "",
        api_base: existingLlmProvider?.api_base ?? DEFAULT_API_BASE,
      };

  const validationSchema = isOnboarding
    ? Yup.object().shape({
        api_key: Yup.string().required("API Key is required"),
        api_base: Yup.string().required("API Base URL is required"),
        default_model_name: Yup.string().required("Model name is required"),
      })
    : buildDefaultValidationSchema().shape({
        api_key: Yup.string().required("API Key is required"),
        api_base: Yup.string().required("API Base URL is required"),
      });

  return (
    <Formik
      initialValues={initialValues}
      validationSchema={validationSchema}
      validateOnMount
      onSubmit={async (values, { setSubmitting }) => {
        if (isOnboarding && onboardingState && onboardingActions) {
          const modelConfigsToUse =
            fetchedModels.length > 0 ? fetchedModels : [];

          await submitOnboardingProvider({
            providerName: OPENROUTER_PROVIDER_NAME,
            payload: {
              ...values,
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
            providerName: OPENROUTER_PROVIDER_NAME,
            values,
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
      {() => (
        <OpenRouterModalInternals
          existingLlmProvider={existingLlmProvider}
          fetchedModels={fetchedModels}
          setFetchedModels={setFetchedModels}
          modelConfigurations={modelConfigurations}
          isTesting={isTesting}
          onClose={onClose}
          isOnboarding={isOnboarding}
        />
      )}
    </Formik>
  );
}
