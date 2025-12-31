import { Form, Formik } from "formik";
import { TextFormField, FileUploadFormField } from "@/components/Field";
import { LLMProviderFormProps } from "../interfaces";
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
import Separator from "@/refresh-components/Separator";

export const VERTEXAI_PROVIDER_NAME = "vertex_ai";
const VERTEXAI_DISPLAY_NAME = "Google Cloud Vertex AI";
const VERTEXAI_DEFAULT_MODEL = "gemini-2.5-pro";
const VERTEXAI_DEFAULT_LOCATION = "global";

interface VertexAIFormValues extends BaseLLMFormValues {
  custom_config: {
    vertex_credentials: string;
    vertex_location: string;
  };
}

export function VertexAIForm({
  existingLlmProvider,
  shouldMarkAsDefault,
}: LLMProviderFormProps) {
  return (
    <ProviderFormEntrypointWrapper
      providerName={VERTEXAI_DISPLAY_NAME}
      providerEndpoint={VERTEXAI_PROVIDER_NAME}
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
        const initialValues: VertexAIFormValues = {
          ...buildDefaultInitialValues(
            existingLlmProvider,
            modelConfigurations
          ),
          default_model_name:
            existingLlmProvider?.default_model_name ??
            wellKnownLLMProvider?.recommended_default_model?.name ??
            VERTEXAI_DEFAULT_MODEL,
          // Default to auto mode for new Vertex AI providers
          is_auto_mode: existingLlmProvider?.is_auto_mode ?? true,
          custom_config: {
            vertex_credentials:
              (existingLlmProvider?.custom_config
                ?.vertex_credentials as string) ?? "",
            vertex_location:
              (existingLlmProvider?.custom_config?.vertex_location as string) ??
              VERTEXAI_DEFAULT_LOCATION,
          },
        };

        const validationSchema = buildDefaultValidationSchema().shape({
          custom_config: Yup.object({
            vertex_credentials: Yup.string().required(
              "Credentials file is required"
            ),
            vertex_location: Yup.string(),
          }),
        });

        return (
          <>
            {popup}
            <Formik
              initialValues={initialValues}
              validationSchema={validationSchema}
              validateOnMount={true}
              onSubmit={async (values, { setSubmitting }) => {
                // Filter out empty custom_config values except for required ones
                const filteredCustomConfig = Object.fromEntries(
                  Object.entries(values.custom_config || {}).filter(
                    ([key, v]) => key === "vertex_credentials" || v !== ""
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
                  providerName: VERTEXAI_PROVIDER_NAME,
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
                return (
                  <Form className={LLM_FORM_CLASS_NAME}>
                    <DisplayNameField disabled={!!existingLlmProvider} />

                    <FileUploadFormField
                      name="custom_config.vertex_credentials"
                      label="Credentials File"
                      subtext="Upload your Google Cloud service account JSON credentials file."
                    />

                    <TextFormField
                      name="custom_config.vertex_location"
                      label="Location"
                      placeholder={VERTEXAI_DEFAULT_LOCATION}
                      subtext="The Google Cloud region for your Vertex AI models (e.g., global, us-east1, us-central1, europe-west1). See [Google's documentation](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/locations#google_model_endpoint_locations) to find the appropriate region for your model."
                      optional
                    />

                    <Separator />

                    <DisplayModels
                      modelConfigurations={modelConfigurations}
                      formikProps={formikProps}
                      recommendedDefaultModel={
                        wellKnownLLMProvider?.recommended_default_model ?? null
                      }
                      shouldShowAutoUpdateToggle={true}
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
