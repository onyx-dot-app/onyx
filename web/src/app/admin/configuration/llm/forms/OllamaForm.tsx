import Separator from "@/refresh-components/Separator";
import { Form, Formik } from "formik";
import { TextFormField } from "@/components/Field";
import {
  LLMProviderView,
  ModelConfiguration,
  OllamaModelResponse,
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
  submitLLMProvider,
  BaseLLMFormValues,
} from "./formUtils";
import { AdvancedOptions } from "./components/AdvancedOptions";
import { DisplayModels } from "./components/DisplayModels";
import { useEffect, useState } from "react";

export const OLLAMA_PROVIDER_NAME = "ollama_chat";
const DEFAULT_API_BASE = "http://127.0.0.1:11434";
const OLLAMA_MODELS_API_URL = "/api/admin/llm/ollama/available-models";

interface OllamaFormValues extends BaseLLMFormValues {
  api_base: string;
  custom_config: {
    OLLAMA_API_KEY?: string;
  };
}

interface OllamaFormProps {
  existingLlmProvider?: LLMProviderView;
  shouldMarkAsDefault?: boolean;
}

export function OllamaForm({
  existingLlmProvider,
  shouldMarkAsDefault,
}: OllamaFormProps) {
  const [availableModels, setAvailableModels] = useState<ModelConfiguration[]>(
    []
  );
  const [isLoadingModels, setIsLoadingModels] = useState(true);

  console.log("availableModels", availableModels);

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
        modelConfigurations,
      }: ProviderFormContext) => {
        const initialValues: OllamaFormValues = {
          ...buildDefaultInitialValues(
            existingLlmProvider,
            modelConfigurations
          ),
          api_base: existingLlmProvider?.api_base ?? DEFAULT_API_BASE,
          default_model_name: existingLlmProvider?.default_model_name ?? "",
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
              {(formikProps) => {
                useEffect(() => {
                  if (formikProps.values.api_base) {
                    fetch(OLLAMA_MODELS_API_URL, {
                      method: "POST",
                      headers: {
                        "Content-Type": "application/json",
                      },
                      body: JSON.stringify({
                        api_base: formikProps.values.api_base,
                      }),
                    })
                      .then((response) => response.json())
                      .then((data: OllamaModelResponse[]) => {
                        setAvailableModels(
                          data.map((model) => ({
                            name: model.name,
                            display_name: model.display_name,
                            is_visible: true,
                            max_input_tokens: model.max_input_tokens,
                            supports_image_input: model.supports_image_input,
                          }))
                        );
                        setIsLoadingModels(false);
                      })
                      .catch((error) => {
                        console.error("Error fetching models:", error);
                        setIsLoadingModels(false);
                      });
                  }
                }, [formikProps.values.api_base]);

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

                    <DisplayModels
                      modelConfigurations={availableModels}
                      formikProps={formikProps}
                      noModelConfigurationsMessage="No models found. Please provide a valid API base URL."
                      isLoading={isLoadingModels}
                    />

                    <AdvancedOptions
                      currentModelConfigurations={availableModels}
                      formikProps={formikProps}
                    />

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
      }}
    </ProviderFormEntrypointWrapper>
  );
}
