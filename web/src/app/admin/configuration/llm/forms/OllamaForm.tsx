import Separator from "@/refresh-components/Separator";
import { Form, Formik } from "formik";
import { SelectorFormField, TextFormField } from "@/components/Field";
import { LLMProviderView, ModelConfiguration } from "../interfaces";
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
  submitLLMProvider,
  BaseLLMFormValues,
} from "./formUtils";
import { AdvancedOptions } from "./components/AdvancedOptions";
import { fetchModels } from "../utils";
import { useState } from "react";
import Button from "@/refresh-components/buttons/Button";
import { LoadingAnimation } from "@/components/Loading";
import Text from "@/refresh-components/texts/Text";

export const OLLAMA_PROVIDER_NAME = "ollama_chat";
const DEFAULT_API_BASE = "http://127.0.0.1:11434";

interface OllamaFormValues extends BaseLLMFormValues {
  api_base: string;
  custom_config: {
    OLLAMA_API_KEY?: string;
  };
  fetched_model_configurations?: ModelConfiguration[];
}

interface OllamaFormProps {
  existingLlmProvider?: LLMProviderView;
  shouldMarkAsDefault?: boolean;
}

interface OllamaFormContentProps extends ProviderFormContext {
  existingLlmProvider?: LLMProviderView;
  shouldMarkAsDefault?: boolean;
}

function OllamaFormContent({
  onClose,
  mutate,
  popup,
  setPopup,
  isTesting,
  setIsTesting,
  testError,
  setTestError,
  modelConfigurations,
  existingLlmProvider,
  shouldMarkAsDefault,
}: OllamaFormContentProps) {
  const [isFetchingModels, setIsFetchingModels] = useState(false);
  const [fetchModelsError, setFetchModelsError] = useState("");

  const initialValues: OllamaFormValues = {
    ...buildDefaultInitialValues(existingLlmProvider, modelConfigurations),
    api_base: existingLlmProvider?.api_base ?? DEFAULT_API_BASE,
    default_model_name: existingLlmProvider?.default_model_name ?? "",
    custom_config: {
      OLLAMA_API_KEY:
        (existingLlmProvider?.custom_config?.OLLAMA_API_KEY as string) ?? "",
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
              values.fetched_model_configurations ?? modelConfigurations,
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
        {(formikProps) => {
          const { values, setFieldValue } = formikProps;

          // Use fetched models if available, otherwise use initial models
          const currentModelConfigurations =
            values.fetched_model_configurations ?? modelConfigurations;

          const handleFetchModels = async () => {
            // Create a minimal descriptor for fetchModels
            const descriptor = {
              name: OLLAMA_PROVIDER_NAME,
              display_name: "Ollama",
              title: "Ollama",
              api_key_required: false,
              api_base_required: true,
              api_version_required: false,
              deployment_name_required: false,
              single_model_supported: false,
              custom_config_keys: null,
              model_configurations: modelConfigurations,
              default_model: null,
              default_api_base: DEFAULT_API_BASE,
              is_public: true,
              groups: [],
            };

            await fetchModels(
              descriptor,
              existingLlmProvider,
              values,
              setFieldValue,
              setIsFetchingModels,
              setFetchModelsError,
              setPopup
            );
          };

          return (
            <Form className="gap-y-4 items-stretch mt-6">
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

              <Separator />

              <div className="flex flex-col gap-y-2">
                <div className="flex items-center gap-x-4">
                  <Button
                    type="button"
                    onClick={handleFetchModels}
                    disabled={isFetchingModels || !values.api_base}
                  >
                    {isFetchingModels ? (
                      <LoadingAnimation />
                    ) : (
                      "Fetch Available Models"
                    )}
                  </Button>
                  {fetchModelsError && (
                    <Text className="text-sm text-error">
                      {fetchModelsError}
                    </Text>
                  )}
                </div>
                {!values.api_base && (
                  <Text mainUiMuted className="text-sm">
                    Enter an API Base URL to fetch available models
                  </Text>
                )}
              </div>

              {currentModelConfigurations.length > 0 && (
                <>
                  <SelectorFormField
                    name="default_model_name"
                    subtext="The model to use by default for this provider unless otherwise specified."
                    label="Default Model"
                    options={currentModelConfigurations.map(
                      (modelConfiguration) => ({
                        name:
                          modelConfiguration.display_name ||
                          modelConfiguration.name,
                        value: modelConfiguration.name,
                      })
                    )}
                    maxHeight="max-h-56"
                  />

                  <Separator />

                  <AdvancedOptions
                    currentModelConfigurations={currentModelConfigurations}
                    formikProps={formikProps}
                  />
                </>
              )}

              <FormActionButtons
                isTesting={isTesting}
                testError={testError}
                existingLlmProvider={existingLlmProvider}
                mutate={mutate}
                onClose={onClose}
              />
            </Form>
          );
        }}
      </Formik>
    </>
  );
}

export function OllamaForm({
  existingLlmProvider,
  shouldMarkAsDefault,
}: OllamaFormProps) {
  return (
    <ProviderFormEntrypointWrapper
      providerName="Ollama"
      providerEndpoint={OLLAMA_PROVIDER_NAME}
      existingLlmProvider={existingLlmProvider}
    >
      {(context: ProviderFormContext) => (
        <OllamaFormContent
          {...context}
          existingLlmProvider={existingLlmProvider}
          shouldMarkAsDefault={shouldMarkAsDefault}
        />
      )}
    </ProviderFormEntrypointWrapper>
  );
}
