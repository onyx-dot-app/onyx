import { Form, Formik } from "formik";
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
import LLMFormLayout from "./components/FormLayout";
import { FormField } from "@/refresh-components/form/FormField";
import InputFile from "@/refresh-components/inputs/InputFile";
import InputSelectField from "@/refresh-components/form/InputSelectField";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import Text from "@/refresh-components/texts/Text";
import { ModelAccessOptions } from "./components/ModelAccessOptions";

export const VERTEXAI_PROVIDER_NAME = "vertex_ai";
const VERTEXAI_DISPLAY_NAME = "Google Cloud Vertex AI";
const VERTEXAI_DEFAULT_MODEL = "gemini-2.5-pro";
const VERTEXAI_DEFAULT_LOCATION = "global";

const VERTEXAI_REGION_OPTIONS = [
  { name: "global", value: "global" },
  { name: "us-central1", value: "us-central1" },
  { name: "us-east1", value: "us-east1" },
  { name: "us-east4", value: "us-east4" },
  { name: "us-east5", value: "us-east5" },
  { name: "us-south1", value: "us-south1" },
  { name: "us-west1", value: "us-west1" },
  { name: "northamerica-northeast1", value: "northamerica-northeast1" },
  { name: "southamerica-east1", value: "southamerica-east1" },
  { name: "europe-west4", value: "europe-west4" },
  { name: "europe-west9", value: "europe-west9" },
  { name: "europe-west2", value: "europe-west2" },
  { name: "europe-west3", value: "europe-west3" },
  { name: "europe-west1", value: "europe-west1" },
  { name: "europe-west6", value: "europe-west6" },
  { name: "europe-southwest1", value: "europe-southwest1" },
  { name: "europe-west8", value: "europe-west8" },
  { name: "europe-north1", value: "europe-north1" },
  { name: "europe-central2", value: "europe-central2" },
  { name: "asia-northeast1", value: "asia-northeast1" },
  { name: "australia-southeast1", value: "australia-southeast1" },
  { name: "asia-southeast1", value: "asia-southeast1" },
  { name: "asia-northeast3", value: "asia-northeast3" },
  { name: "asia-east1", value: "asia-east1" },
  { name: "asia-east2", value: "asia-east2" },
  { name: "asia-south1", value: "asia-south1" },
  { name: "me-central2", value: "me-central2" },
  { name: "me-central1", value: "me-central1" },
  { name: "me-west1", value: "me-west1" },
];

const VERTEXAI_REGION_NAME = "custom_config.vertex_location";

interface VertexAIFormValues extends BaseLLMFormValues {
  custom_config: {
    vertex_credentials: string;
    vertex_location: string;
  };
}

export function VertexAIForm({
  existingLlmProvider,
  defaultLlmModel,
  shouldMarkAsDefault,
}: LLMProviderFormProps) {
  return (
    <ProviderFormEntrypointWrapper
      providerName={VERTEXAI_DISPLAY_NAME}
      providerDisplayName={existingLlmProvider?.name ?? "Gemini"}
      providerInternalName={"vertex_ai"}
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

        const isAutoMode = existingLlmProvider?.is_auto_mode ?? true;
        const autoModelDefault =
          wellKnownLLMProvider?.recommended_default_model?.name ??
          VERTEXAI_DEFAULT_MODEL;

        const defaultModel = shouldMarkAsDefault
          ? isAutoMode
            ? autoModelDefault
            : defaultLlmModel?.model_name ?? VERTEXAI_DEFAULT_MODEL
          : undefined;

        const initialValues: VertexAIFormValues = {
          ...buildDefaultInitialValues(
            existingLlmProvider,
            modelConfigurations,
            defaultModel
          ),
          // Default to auto mode for new Vertex AI providers
          is_auto_mode: isAutoMode,
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
                    <LLMFormLayout.Body>
                      <InputSelectField name={VERTEXAI_REGION_NAME}>
                        <Text as="p">Google Cloud Region Name</Text>
                        <InputSelect.Trigger placeholder="Select region" />
                        <InputSelect.Content>
                          {VERTEXAI_REGION_OPTIONS.map((option) => (
                            <InputSelect.Item
                              key={option.value}
                              value={option.value}
                            >
                              {option.name}
                            </InputSelect.Item>
                          ))}
                        </InputSelect.Content>
                      </InputSelectField>

                      <FormField
                        name="custom_config.vertex_credentials"
                        state={
                          formikProps.errors.custom_config?.vertex_credentials
                            ? "error"
                            : "idle"
                        }
                      >
                        <FormField.Label>API Key</FormField.Label>
                        <FormField.Control>
                          <InputFile
                            setValue={(value) =>
                              formikProps.setFieldValue(
                                "custom_config.vertex_credentials",
                                value
                              )
                            }
                            error={
                              !!formikProps.errors.custom_config
                                ?.vertex_credentials
                            }
                            onBlur={formikProps.handleBlur}
                            showClearButton={true}
                            disabled={formikProps.isSubmitting}
                            accept="application/json"
                            placeholder="Vertex AI API KEY (JSON)"
                          />
                        </FormField.Control>
                      </FormField>
                    </LLMFormLayout.Body>

                    <DisplayNameField disabled={!!existingLlmProvider} />

                    <Separator noPadding />

                    <DisplayModels
                      modelConfigurations={modelConfigurations}
                      formikProps={formikProps}
                      shouldShowAutoUpdateToggle={true}
                    />

                    <ModelAccessOptions />

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
