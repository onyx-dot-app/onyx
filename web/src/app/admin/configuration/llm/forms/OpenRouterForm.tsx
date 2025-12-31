import Separator from "@/refresh-components/Separator";
import { Form, Formik } from "formik";
import { TextFormField } from "@/components/Field";
import {
  LLMProviderFormProps,
  ModelConfiguration,
  OpenRouterModelResponse,
} from "../interfaces";
import * as Yup from "yup";
import {
  ProviderFormEntrypointWrapper,
  ProviderFormContext,
} from "./components/FormWrapper";
import { DisplayNameField } from "./components/DisplayNameField";
import { ApiKeyField } from "./components/ApiKeyField";
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
import { FetchModelsButton } from "./components/FetchModelsButton";
import { useState } from "react";

export const OPENROUTER_PROVIDER_NAME = "openrouter";
const OPENROUTER_DISPLAY_NAME = "OpenRouter";
const DEFAULT_API_BASE = "https://openrouter.ai/api/v1";
const OPENROUTER_MODELS_API_URL = "/api/admin/llm/openrouter/available-models";

interface OpenRouterFormValues extends BaseLLMFormValues {
  api_key: string;
  api_base: string;
}

async function fetchOpenRouterModels(params: {
  apiBase: string;
  apiKey: string;
  providerName?: string;
}): Promise<{ models: ModelConfiguration[]; error?: string }> {
  if (!params.apiBase || !params.apiKey) {
    return {
      models: [],
      error: "API Base and API Key are required to fetch models",
    };
  }

  try {
    const response = await fetch(OPENROUTER_MODELS_API_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        api_base: params.apiBase,
        api_key: params.apiKey,
        provider_name: params.providerName,
      }),
    });

    if (!response.ok) {
      let errorMessage = "Failed to fetch models";
      try {
        const errorData = await response.json();
        errorMessage = errorData.detail || errorMessage;
      } catch {
        // ignore JSON parsing errors
      }
      return { models: [], error: errorMessage };
    }

    const data: OpenRouterModelResponse[] = await response.json();
    const models: ModelConfiguration[] = data.map((modelData) => ({
      name: modelData.name,
      display_name: modelData.display_name,
      is_visible: true,
      max_input_tokens: modelData.max_input_tokens,
      supports_image_input: modelData.supports_image_input,
    }));

    return { models };
  } catch (error) {
    const errorMessage =
      error instanceof Error ? error.message : "Unknown error";
    return { models: [], error: errorMessage };
  }
}

export function OpenRouterForm({
  existingLlmProvider,
  shouldMarkAsDefault,
}: LLMProviderFormProps) {
  const [fetchedModels, setFetchedModels] = useState<ModelConfiguration[]>([]);

  return (
    <ProviderFormEntrypointWrapper
      providerName={OPENROUTER_DISPLAY_NAME}
      providerEndpoint={OPENROUTER_PROVIDER_NAME}
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
        const initialValues: OpenRouterFormValues = {
          ...buildDefaultInitialValues(
            existingLlmProvider,
            modelConfigurations
          ),
          api_key: existingLlmProvider?.api_key ?? "",
          api_base: existingLlmProvider?.api_base ?? DEFAULT_API_BASE,
        };

        const validationSchema = buildDefaultValidationSchema().shape({
          api_key: Yup.string().required("API Key is required"),
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
                await submitLLMProvider({
                  providerName: OPENROUTER_PROVIDER_NAME,
                  values,
                  initialValues,
                  modelConfigurations:
                    fetchedModels.length > 0
                      ? fetchedModels
                      : modelConfigurations,
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
                const currentModels =
                  fetchedModels.length > 0
                    ? fetchedModels
                    : existingLlmProvider?.model_configurations ||
                      modelConfigurations;

                const isFetchDisabled =
                  !formikProps.values.api_base || !formikProps.values.api_key;

                return (
                  <Form className={LLM_FORM_CLASS_NAME}>
                    <DisplayNameField disabled={!!existingLlmProvider} />

                    <ApiKeyField />

                    <TextFormField
                      name="api_base"
                      label="API Base URL"
                      subtext="The base URL for OpenRouter API."
                      placeholder={DEFAULT_API_BASE}
                    />

                    <FetchModelsButton
                      onFetch={() =>
                        fetchOpenRouterModels({
                          apiBase: formikProps.values.api_base,
                          apiKey: formikProps.values.api_key,
                          providerName: existingLlmProvider?.name,
                        })
                      }
                      isDisabled={isFetchDisabled}
                      disabledHint={
                        !formikProps.values.api_key
                          ? "Enter your API key first."
                          : !formikProps.values.api_base
                            ? "Enter the API base URL."
                            : undefined
                      }
                      onModelsFetched={setFetchedModels}
                      autoFetchOnInitialLoad={!!existingLlmProvider}
                    />

                    <Separator />

                    <DisplayModels
                      modelConfigurations={currentModels}
                      formikProps={formikProps}
                      noModelConfigurationsMessage={
                        "Fetch available models first, then you'll be able to select " +
                        "the models you want to make available in Onyx."
                      }
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
                      isFormValid={formikProps.isValid}
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
