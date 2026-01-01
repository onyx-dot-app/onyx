import { Form, Formik, FormikProps } from "formik";
import { TextFormField } from "@/components/Field";
import {
  LLMProviderFormProps,
  LLMProviderView,
  ModelConfiguration,
} from "../interfaces";
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
import { fetchOllamaModels } from "../utils";

export const OLLAMA_PROVIDER_NAME = "ollama_chat";
const DEFAULT_API_BASE = "http://127.0.0.1:11434";

interface OllamaFormValues extends BaseLLMFormValues {
  api_base: string;
  custom_config: {
    OLLAMA_API_KEY?: string;
  };
}

interface OllamaFormContentProps {
  formikProps: FormikProps<OllamaFormValues>;
  existingLlmProvider?: LLMProviderView;
  isTesting: boolean;
  testError: string;
  mutate: () => void;
  onClose: () => void;
  isFormValid: boolean;
}

function OllamaFormContent({
  formikProps,
  existingLlmProvider,
  isTesting,
  testError,
  mutate,
  onClose,
  isFormValid,
}: OllamaFormContentProps) {
  const [availableModels, setAvailableModels] = useState<ModelConfiguration[]>(
    existingLlmProvider?.model_configurations || []
  );
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
            setAvailableModels([]);
            return;
          }
          setAvailableModels(data.models);
        })
        .finally(() => {
          setIsLoadingModels(false);
        });
    }
  }, [formikProps.values.api_base]);

  return (
    <Form className={LLM_FORM_CLASS_NAME}>
      <DisplayNameField disabled={!!existingLlmProvider} />

      <TextFormField
        name="api_base"
        label="API Base URL"
        subtext="The base URL for your Ollama instance (e.g., http://127.0.0.1:11434)"
        placeholder={DEFAULT_API_BASE}
      />

      <TextFormField
        name="custom_config.OLLAMA_API_KEY"
        label="API Key (Optional)"
        subtext="Optional API key for Ollama Cloud (https://ollama.com). Leave blank for local instances."
        placeholder=""
        type="password"
        showPasswordToggle
      />

      <DisplayModels
        modelConfigurations={availableModels}
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

export function OllamaForm({
  existingLlmProvider,
  shouldMarkAsDefault,
}: LLMProviderFormProps) {
  return (
    <ProviderFormEntrypointWrapper
      providerName="Ollama"
      existingLlmProvider={existingLlmProvider}
    >
      {({
        onClose,
        mutate,
        popup,
        setPopup,
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
        const initialValues: OllamaFormValues = {
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
          <>
            {popup}
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
                  modelConfigurations,
                  existingLlmProvider,
                  shouldMarkAsDefault,
                  setIsTesting,
                  setTestError,
                  setPopup,
                  mutate,
                  onClose,
                  setSubmitting,
                });
              }}
            >
              {(formikProps) => (
                <OllamaFormContent
                  formikProps={formikProps}
                  existingLlmProvider={existingLlmProvider}
                  isTesting={isTesting}
                  testError={testError}
                  mutate={mutate}
                  onClose={onClose}
                  isFormValid={formikProps.isValid}
                />
              )}
            </Formik>
          </>
        );
      }}
    </ProviderFormEntrypointWrapper>
  );
}
