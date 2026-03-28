"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSWRConfig } from "swr";
import { Formik, FormikProps } from "formik";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import * as InputLayouts from "@/layouts/input-layouts";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import {
  LLMProviderFormProps,
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
  SingleDefaultModelField,
  LLMConfigurationModalWrapper,
} from "@/sections/modals/llmConfig/shared";
import { fetchOllamaModels } from "@/app/admin/configuration/llm/utils";
import debounce from "lodash/debounce";
import Tabs from "@/refresh-components/Tabs";
import { Card } from "@opal/components";
import { toast } from "@/hooks/useToast";

const OLLAMA_PROVIDER_NAME = "ollama_chat";
const DEFAULT_API_BASE = "http://127.0.0.1:11434";
const TAB_SELF_HOSTED = "self-hosted";
const TAB_CLOUD = "cloud";

interface OllamaModalValues extends BaseLLMFormValues {
  api_base: string;
  custom_config: {
    OLLAMA_API_KEY?: string;
  };
}

interface OllamaModalInternalsProps {
  formikProps: FormikProps<OllamaModalValues>;
  existingLlmProvider: LLMProviderView | undefined;
  fetchedModels: ModelConfiguration[];
  setFetchedModels: (models: ModelConfiguration[]) => void;
  isTesting: boolean;
  onClose: () => void;
  isOnboarding: boolean;
  maxTokenOverrides: Record<string, number | null>;
  onMaxInputTokensChange: (modelName: string, value: number | null) => void;
}

function OllamaModalInternals({
  formikProps,
  existingLlmProvider,
  fetchedModels,
  setFetchedModels,
  isTesting,
  onClose,
  isOnboarding,
  maxTokenOverrides,
  onMaxInputTokensChange,
}: OllamaModalInternalsProps) {
  const isInitialMount = useRef(true);

  const doFetchModels = useCallback(
    (apiBase: string, signal: AbortSignal) => {
      fetchOllamaModels({
        api_base: apiBase,
        provider_name: existingLlmProvider?.name,
        signal,
      }).then((data) => {
        if (signal.aborted) return;
        if (data.error) {
          toast.error(data.error);
          setFetchedModels([]);
          return;
        }
        setFetchedModels(data.models);
      });
    },
    [existingLlmProvider?.name, setFetchedModels]
  );

  const debouncedFetchModels = useMemo(
    () => debounce(doFetchModels, 500),
    [doFetchModels]
  );

  // Skip the initial fetch for new providers — api_base starts with a default
  // value, which would otherwise trigger a fetch before the user has done
  // anything. Existing providers should still auto-fetch on mount.
  useEffect(() => {
    if (isInitialMount.current) {
      isInitialMount.current = false;
      if (!existingLlmProvider) return;
    }

    if (formikProps.values.api_base) {
      const controller = new AbortController();
      debouncedFetchModels(formikProps.values.api_base, controller.signal);
      return () => {
        debouncedFetchModels.cancel();
        controller.abort();
      };
    } else {
      setFetchedModels([]);
    }
  }, [
    formikProps.values.api_base,
    debouncedFetchModels,
    setFetchedModels,
    existingLlmProvider,
  ]);

  const baseModels =
    fetchedModels.length > 0
      ? fetchedModels
      : existingLlmProvider?.model_configurations || [];

  const currentModels = baseModels.map((m) =>
    m.name in maxTokenOverrides
      ? { ...m, max_input_tokens: maxTokenOverrides[m.name] }
      : m
  );

  const hasApiKey = !!formikProps.values.custom_config?.OLLAMA_API_KEY;
  const defaultTab =
    existingLlmProvider && hasApiKey ? TAB_CLOUD : TAB_SELF_HOSTED;

  return (
    <LLMConfigurationModalWrapper
      providerEndpoint={OLLAMA_PROVIDER_NAME}
      existingProviderName={existingLlmProvider?.name}
      onClose={onClose}
      isFormValid={formikProps.isValid}
      isDirty={formikProps.dirty || Object.keys(maxTokenOverrides).length > 0}
      isTesting={isTesting}
      isSubmitting={formikProps.isSubmitting}
    >
      <Card backgroundVariant="light" borderVariant="none" sizeVariant="lg">
        <Tabs defaultValue={defaultTab}>
          <Tabs.List>
            <Tabs.Trigger value={TAB_SELF_HOSTED}>
              Self-hosted Ollama
            </Tabs.Trigger>
            <Tabs.Trigger value={TAB_CLOUD}>Ollama Cloud</Tabs.Trigger>
          </Tabs.List>
          <Tabs.Content value={TAB_SELF_HOSTED}>
            <InputLayouts.Vertical
              name="api_base"
              title="API Base URL"
              subDescription="The base URL for your Ollama instance."
            >
              <InputTypeInField
                name="api_base"
                placeholder="Your Ollama API base URL"
              />
            </InputLayouts.Vertical>
          </Tabs.Content>

          <Tabs.Content value={TAB_CLOUD}>
            <InputLayouts.Vertical
              name="custom_config.OLLAMA_API_KEY"
              title="API Key"
              subDescription="Your Ollama Cloud API key."
            >
              <PasswordInputTypeInField
                name="custom_config.OLLAMA_API_KEY"
                placeholder="API Key"
              />
            </InputLayouts.Vertical>
          </Tabs.Content>
        </Tabs>
      </Card>

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
          showMaxInputTokens
          onMaxInputTokensChange={onMaxInputTokensChange}
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

export default function OllamaModal({
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
  const [maxTokenOverrides, setMaxTokenOverrides] = useState<
    Record<string, number | null>
  >({});
  const [isTesting, setIsTesting] = useState(false);
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();
  const { wellKnownLLMProvider } =
    useWellKnownLLMProvider(OLLAMA_PROVIDER_NAME);

  const handleMaxInputTokensChange = useCallback(
    (modelName: string, value: number | null) => {
      setMaxTokenOverrides((prev) => ({ ...prev, [modelName]: value }));
    },
    []
  );

  const applyMaxTokenOverrides = useCallback(
    (configs: ModelConfiguration[]): ModelConfiguration[] =>
      configs.map((m) =>
        m.name in maxTokenOverrides
          ? { ...m, max_input_tokens: maxTokenOverrides[m.name] }
          : m
      ),
    [maxTokenOverrides]
  );

  if (open === false) return null;

  const onClose = () => onOpenChange?.(false);

  const modelConfigurations = buildAvailableModelConfigurations(
    existingLlmProvider,
    wellKnownLLMProvider ?? llmDescriptor
  );

  const initialValues: OllamaModalValues = isOnboarding
    ? ({
        ...buildOnboardingInitialValues(),
        name: OLLAMA_PROVIDER_NAME,
        provider: OLLAMA_PROVIDER_NAME,
        api_base: DEFAULT_API_BASE,
        default_model_name: "",
        custom_config: {
          OLLAMA_API_KEY: "",
        },
      } as OllamaModalValues)
    : {
        ...buildDefaultInitialValues(
          existingLlmProvider,
          modelConfigurations,
          defaultModelName
        ),
        api_base: existingLlmProvider?.api_base ?? DEFAULT_API_BASE,
        custom_config: {
          OLLAMA_API_KEY:
            (existingLlmProvider?.custom_config?.OLLAMA_API_KEY as string) ??
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
          const modelConfigsToUse = applyMaxTokenOverrides(
            fetchedModels.length > 0 ? fetchedModels : []
          );

          await submitOnboardingProvider({
            providerName: OLLAMA_PROVIDER_NAME,
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
          const configsToSubmit = applyMaxTokenOverrides(
            fetchedModels.length > 0 ? fetchedModels : modelConfigurations
          );

          await submitLLMProvider({
            providerName: OLLAMA_PROVIDER_NAME,
            values: submitValues,
            initialValues,
            modelConfigurations: configsToSubmit,
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
        <OllamaModalInternals
          formikProps={formikProps}
          existingLlmProvider={existingLlmProvider}
          fetchedModels={fetchedModels}
          setFetchedModels={setFetchedModels}
          isTesting={isTesting}
          onClose={onClose}
          isOnboarding={isOnboarding}
          maxTokenOverrides={maxTokenOverrides}
          onMaxInputTokensChange={handleMaxInputTokensChange}
        />
      )}
    </Formik>
  );
}
