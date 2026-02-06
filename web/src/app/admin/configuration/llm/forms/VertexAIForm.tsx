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

export const VERTEXAI_PROVIDER_NAME = "vertex_ai";
const VERTEXAI_DISPLAY_NAME = "Google Cloud Vertex AI";
const VERTEXAI_DEFAULT_MODEL = "gemini-2.5-pro";
const VERTEXAI_DEFAULT_LOCATION = "global";

const VERTEXAI_REGION_OPTIONS = [{ name: "global", value: "global" }];

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
