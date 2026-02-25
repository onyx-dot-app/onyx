import { Form, Formik, FormikProps } from "formik";
import { TextFormField } from "@/components/Field";
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
import { FormActionButtons } from "./components/FormActionButtons";
import {
  buildDefaultInitialValues,
  buildDefaultValidationSchema,
  buildAvailableModelConfigurations,
  submitLLMProvider,
  BaseLLMFormValues,
  LLM_FORM_CLASS_NAME,
} from "./formUtils";
import { AdvancedOptions } from "./components/AdvancedOptions";
import { DisplayModels } from "./components/DisplayModels";
import { useEffect, useState } from "react";
import { fetchOllamaModels } from "@/app/admin/configuration/llm/utils";

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
  mutate: () => void;
  onClose: () => void;
  isFormValid: boolean;
}

function OllamaModalContent({
  formikProps,
  existingLlmProvider,
  fetchedModels,
  setFetchedModels,
  isTesting,
  testError,
  mutate,
  onClose,
  isFormValid,
}: OllamaModalContentProps) {
  const [isLoadingModels, setIsLoadingModels] = useState(true);

  useEffect(() => {
    if (formikProps.values.api_base) {
      setIsLoadingModels(true);
      fetchOllamaModels({
        api_base: formikProps.values.api_base,
        provider_name: existingLlmProvider?.name,
      })
        .then((data) => {
          if (data.error) {
            console.error("Error fetching models:", data.error);
            setFetchedModels([]);
            return;
          }
          setFetchedModels(data.models);
        })
        .finally(() => {
          setIsLoadingModels(false);
        });
    }
  }, [
    formikProps.values.api_base,
    existingLlmProvider?.name,
    setFetchedModels,
  ]);

  const currentModels =
    fetchedModels.length > 0
      ? fetchedModels
      : existingLlmProvider?.model_configurations || [];

  return (
    <Form className={LLM_FORM_CLASS_NAME}>
      <DisplayNameField disabled={!!existingLlmProvider} />

      <TextFormField
        name="api_base"
        label="API Base URL"
        subtext="The base URL for your Ollama instance (e.g., http://127.0.0.1:11434)"
        placeholder={DEFAULT_API_BASE}
      />

      <PasswordInputTypeInField
        name="custom_config.OLLAMA_API_KEY"
        label="API Key (Optional)"
        subtext="Optional API key for Ollama Cloud (https://ollama.com). Leave blank for local instances."
      />

      <DisplayModels
        modelConfigurations={currentModels}
        formikProps={formikProps}
        noModelConfigurationsMessage="No models found. Please provide a valid API base URL."
        isLoading={isLoadingModels}
        recommendedDefaultModel={null}
        shouldShowAutoUpdateToggle={false}
      />

      <AdvancedOptions formikProps={formikProps} />

      <FormActionButtons
        isTesting={isTesting}
        testError={testError}
        existingLlmProvider={existingLlmProvider}
        mutate={mutate}
        onClose={onClose}
        isFormValid={isFormValid}
      />
    </Form>
  );
}

export function OllamaModal({
  existingLlmProvider,
  shouldMarkAsDefault,
  open,
  onOpenChange,
}: LLMProviderFormProps) {
  const [fetchedModels, setFetchedModels] = useState<ModelConfiguration[]>([]);

  return (
    <ProviderFormEntrypointWrapper
      providerName="Ollama"
      existingLlmProvider={existingLlmProvider}
      open={open}
      onOpenChange={onOpenChange}
    >
      {({
        onClose,
        mutate,
        isTesting,
        setIsTesting,
        testError,
        setTestError,
        wellKnownLLMProvider,
      }: ProviderFormContext) => {
        const modelConfigurations = buildAvailableModelConfigurations(
          existingLlmProvider,
          wellKnownLLMProvider
        );
        const initialValues: OllamaModalValues = {
          ...buildDefaultInitialValues(
            existingLlmProvider,
            modelConfigurations
          ),
          api_base: existingLlmProvider?.api_base ?? DEFAULT_API_BASE,
          custom_config: {
            OLLAMA_API_KEY:
              (existingLlmProvider?.custom_config?.OLLAMA_API_KEY as string) ??
              "",
          },
        };

        const validationSchema = buildDefaultValidationSchema().shape({
          api_base: Yup.string().required("API Base URL is required"),
        });

        return (
          <Formik
            initialValues={initialValues}
            validationSchema={validationSchema}
            validateOnMount={true}
            onSubmit={async (values, { setSubmitting }) => {
              // Filter out empty custom_config values
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
                mutate={mutate}
                onClose={onClose}
                isFormValid={formikProps.isValid}
              />
            )}
          </Formik>
        );
      }}
    </ProviderFormEntrypointWrapper>
  );
}
