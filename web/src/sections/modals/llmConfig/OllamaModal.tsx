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
import {
  ProviderFormEntrypointWrapper,
  ProviderFormContext,
} from "./components/FormWrapper";
import { DisplayNameField } from "./components/DisplayNameField";
import { LLMConfigurationModalWrapper } from "./shared";
import {
  buildDefaultInitialValues,
  buildDefaultValidationSchema,
  buildAvailableModelConfigurations,
  submitLLMProvider,
  submitOnboardingProvider,
  buildOnboardingInitialValues,
  BaseLLMFormValues,
} from "./formUtils";
import { AdvancedOptions } from "./components/AdvancedOptions";
import { DisplayModels } from "./components/DisplayModels";
import { SingleDefaultModelField } from "./components/SingleDefaultModelField";
import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchOllamaModels } from "@/app/admin/configuration/llm/utils";
import debounce from "lodash/debounce";

export const OLLAMA_PROVIDER_NAME = "ollama_chat";
const DEFAULT_API_BASE = "http://127.0.0.1:11434";

interface OllamaModalValues extends BaseLLMFormValues {
  api_base: string;
  custom_config: {
    OLLAMA_API_KEY?: string;
  };
}

interface OllamaModalContentProps {
  formikProps: FormikProps<OllamaModalValues>;
  existingLlmProvider?: LLMProviderView;
  fetchedModels: ModelConfiguration[];
  setFetchedModels: (models: ModelConfiguration[]) => void;
  isTesting: boolean;
  testError: string;
  onClose: () => void;
  isFormValid: boolean;
  isOnboarding: boolean;
}

function OllamaModalContent({
  formikProps,
  existingLlmProvider,
  fetchedModels,
  setFetchedModels,
  isTesting,
  testError,
  onClose,
  isFormValid,
  isOnboarding,
}: OllamaModalContentProps) {
  const [isLoadingModels, setIsLoadingModels] = useState(true);

  const fetchModels = useCallback(
    (apiBase: string, signal: AbortSignal) => {
      setIsLoadingModels(true);
      fetchOllamaModels({
        api_base: apiBase,
        provider_name: existingLlmProvider?.name,
        signal,
      })
        .then((data) => {
          if (signal.aborted) return;
          if (data.error) {
            console.error("Error fetching models:", data.error);
            setFetchedModels([]);
            return;
          }
          setFetchedModels(data.models);
        })
        .finally(() => {
          if (!signal.aborted) {
            setIsLoadingModels(false);
          }
        });
    },
    [existingLlmProvider?.name, setFetchedModels]
  );

  const debouncedFetchModels = useMemo(
    () => debounce(fetchModels, 500),
    [fetchModels]
  );

  useEffect(() => {
    if (formikProps.values.api_base) {
      const controller = new AbortController();
      debouncedFetchModels(formikProps.values.api_base, controller.signal);
      return () => {
        debouncedFetchModels.cancel();
        controller.abort();
      };
    } else {
      setIsLoadingModels(false);
      setFetchedModels([]);
    }
  }, [formikProps.values.api_base, debouncedFetchModels, setFetchedModels]);

  const currentModels =
    fetchedModels.length > 0
      ? fetchedModels
      : existingLlmProvider?.model_configurations || [];

  return (
    <LLMConfigurationModalWrapper
      providerEndpoint={OLLAMA_PROVIDER_NAME}
      existingProviderName={existingLlmProvider?.name}
      onClose={onClose}
      isFormValid={isFormValid}
      isTesting={isTesting}
      testError={testError}
    >
      {!isOnboarding && <DisplayNameField disabled={!!existingLlmProvider} />}

      <InputLayouts.Vertical
        name="api_base"
        title="API Base URL"
        description="The base URL for your Ollama instance (e.g., http://127.0.0.1:11434)"
      >
        <InputTypeInField name="api_base" placeholder={DEFAULT_API_BASE} />
      </InputLayouts.Vertical>

      <PasswordInputTypeInField
        name="custom_config.OLLAMA_API_KEY"
        label="API Key (Optional)"
        subtext="Optional API key for Ollama Cloud (https://ollama.com). Leave blank for local instances."
      />

      {isOnboarding ? (
        <SingleDefaultModelField placeholder="E.g. llama3.1" />
      ) : (
        <DisplayModels
          modelConfigurations={currentModels}
          formikProps={formikProps}
          noModelConfigurationsMessage="No models found. Please provide a valid API base URL."
          isLoading={isLoadingModels}
          recommendedDefaultModel={null}
          shouldShowAutoUpdateToggle={false}
        />
      )}

      {!isOnboarding && <AdvancedOptions formikProps={formikProps} />}
    </LLMConfigurationModalWrapper>
  );
}

export function OllamaModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  open,
  onOpenChange,
  onboardingState,
  onboardingActions,
  llmDescriptor,
}: LLMProviderFormProps) {
  const [fetchedModels, setFetchedModels] = useState<ModelConfiguration[]>([]);
  const isOnboarding = variant === "onboarding";

  return (
    <ProviderFormEntrypointWrapper
      providerName="Ollama"
      providerEndpoint={OLLAMA_PROVIDER_NAME}
      existingLlmProvider={existingLlmProvider}
      open={open}
      onOpenChange={onOpenChange}
      variant={variant}
      onboardingState={onboardingState}
      onboardingActions={onboardingActions}
    >
      {({
        onClose,
        mutate,
        isTesting,
        setIsTesting,
        testError,
        setTestError,
        wellKnownLLMProvider,
        onboardingState: ctxOnboardingState,
        onboardingActions: ctxOnboardingActions,
      }: ProviderFormContext) => {
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
                modelConfigurations
              ),
              api_base: existingLlmProvider?.api_base ?? DEFAULT_API_BASE,
              custom_config: {
                OLLAMA_API_KEY:
                  (existingLlmProvider?.custom_config
                    ?.OLLAMA_API_KEY as string) ?? "",
              },
            };

        const validationSchema = isOnboarding
          ? Yup.object().shape({
              api_base: Yup.string().required("API Base URL is required"),
              default_model_name: Yup.string().required(
                "Model name is required"
              ),
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
                Object.entries(values.custom_config || {}).filter(
                  ([, v]) => v !== ""
                )
              );

              const submitValues = {
                ...values,
                custom_config:
                  Object.keys(filteredCustomConfig).length > 0
                    ? filteredCustomConfig
                    : undefined,
              };

              if (isOnboarding && ctxOnboardingState && ctxOnboardingActions) {
                const modelConfigsToUse =
                  fetchedModels.length > 0 ? fetchedModels : [];

                await submitOnboardingProvider({
                  providerName: OLLAMA_PROVIDER_NAME,
                  payload: {
                    ...submitValues,
                    model_configurations: modelConfigsToUse,
                  },
                  onboardingState: ctxOnboardingState,
                  onboardingActions: ctxOnboardingActions,
                  isCustomProvider: false,
                  onClose,
                  setIsSubmitting: setSubmitting,
                  setApiStatus: () => {},
                  setShowApiMessage: () => {},
                  setErrorMessage: (msg) => setTestError(msg),
                });
              } else {
                await submitLLMProvider({
                  providerName: OLLAMA_PROVIDER_NAME,
                  values: submitValues,
                  initialValues,
                  modelConfigurations:
                    fetchedModels.length > 0
                      ? fetchedModels
                      : modelConfigurations,
                  existingLlmProvider,
                  shouldMarkAsDefault,
                  setIsTesting,
                  setTestError,
                  mutate,
                  onClose,
                  setSubmitting,
                });
              }
            }}
          >
            {(formikProps) => (
              <OllamaModalContent
                formikProps={formikProps}
                existingLlmProvider={existingLlmProvider}
                fetchedModels={fetchedModels}
                setFetchedModels={setFetchedModels}
                isTesting={isTesting}
                testError={testError}
                onClose={onClose}
                isFormValid={formikProps.isValid}
                isOnboarding={isOnboarding}
              />
            )}
          </Formik>
        );
      }}
    </ProviderFormEntrypointWrapper>
  );
}
