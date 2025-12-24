import { Form, Formik } from "formik";
import { TextFormField, FileUploadFormField } from "@/components/Field";
import { LLMProviderView } from "../interfaces";
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
  LLM_FORM_CLASS_NAME,
} from "./formUtils";
import { AdvancedOptions } from "./components/AdvancedOptions";
import { DisplayModels } from "./components/DisplayModels";
import Separator from "@/refresh-components/Separator";

export const VERTEXAI_PROVIDER_NAME = "vertex_ai";
const VERTEXAI_DISPLAY_NAME = "Google Cloud Vertex AI";
const VERTEXAI_DEFAULT_MODEL = "gemini-2.5-pro";
const VERTEXAI_DEFAULT_LOCATION = "us-east1";

interface VertexAIFormValues extends BaseLLMFormValues {
  custom_config: {
    vertex_credentials: string;
    vertex_location: string;
  };
}

interface VertexAIFormProps {
  existingLlmProvider?: LLMProviderView;
  shouldMarkAsDefault?: boolean;
}

export function VertexAIForm({
  existingLlmProvider,
  shouldMarkAsDefault,
}: VertexAIFormProps) {
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
        modelConfigurations,
      }: ProviderFormContext) => {
        const initialValues: VertexAIFormValues = {
          ...buildDefaultInitialValues(
            existingLlmProvider,
            modelConfigurations
          ),
          default_model_name:
            existingLlmProvider?.default_model_name ?? VERTEXAI_DEFAULT_MODEL,
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
                      subtext="The Google Cloud region for your Vertex AI models (e.g., us-east1, us-central1, europe-west1)."
                      optional
                    />

                    <Separator />

                    <DisplayModels
                      modelConfigurations={modelConfigurations}
                      formikProps={formikProps}
                    />

                    <AdvancedOptions
                      currentModelConfigurations={modelConfigurations}
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
