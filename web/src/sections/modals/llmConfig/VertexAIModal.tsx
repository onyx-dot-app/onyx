import { Formik } from "formik";
import { FileUploadFormField } from "@/components/Field";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import * as InputLayouts from "@/layouts/input-layouts";
import { LLMProviderFormProps } from "@/interfaces/llm";
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
import Separator from "@/refresh-components/Separator";

export const VERTEXAI_PROVIDER_NAME = "vertex_ai";
const VERTEXAI_DISPLAY_NAME = "Google Cloud Vertex AI";
const VERTEXAI_DEFAULT_MODEL = "gemini-2.5-pro";
const VERTEXAI_DEFAULT_LOCATION = "global";

interface VertexAIModalValues extends BaseLLMFormValues {
  custom_config: {
    vertex_credentials: string;
    vertex_location: string;
  };
}

export function VertexAIModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  open,
  onOpenChange,
  onboardingState,
  onboardingActions,
  llmDescriptor,
}: LLMProviderFormProps) {
  const isOnboarding = variant === "onboarding";

  return (
    <ProviderFormEntrypointWrapper
      providerName={VERTEXAI_DISPLAY_NAME}
      providerEndpoint={VERTEXAI_PROVIDER_NAME}
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

        const initialValues: VertexAIModalValues = isOnboarding
          ? ({
              ...buildOnboardingInitialValues(),
              name: VERTEXAI_PROVIDER_NAME,
              provider: VERTEXAI_PROVIDER_NAME,
              default_model_name: VERTEXAI_DEFAULT_MODEL,
              custom_config: {
                vertex_credentials: "",
                vertex_location: VERTEXAI_DEFAULT_LOCATION,
              },
            } as VertexAIModalValues)
          : {
              ...buildDefaultInitialValues(
                existingLlmProvider,
                modelConfigurations
              ),
              default_model_name:
                wellKnownLLMProvider?.recommended_default_model?.name ??
                VERTEXAI_DEFAULT_MODEL,
              is_auto_mode: existingLlmProvider?.is_auto_mode ?? true,
              custom_config: {
                vertex_credentials:
                  (existingLlmProvider?.custom_config
                    ?.vertex_credentials as string) ?? "",
                vertex_location:
                  (existingLlmProvider?.custom_config
                    ?.vertex_location as string) ?? VERTEXAI_DEFAULT_LOCATION,
              },
            };

        const validationSchema = isOnboarding
          ? Yup.object().shape({
              default_model_name: Yup.string().required(
                "Model name is required"
              ),
              custom_config: Yup.object({
                vertex_credentials: Yup.string().required(
                  "Credentials file is required"
                ),
                vertex_location: Yup.string(),
              }),
            })
          : buildDefaultValidationSchema().shape({
              custom_config: Yup.object({
                vertex_credentials: Yup.string().required(
                  "Credentials file is required"
                ),
                vertex_location: Yup.string(),
              }),
            });

        return (
          <Formik
            initialValues={initialValues}
            validationSchema={validationSchema}
            validateOnMount={true}
            onSubmit={async (values, { setSubmitting }) => {
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

              if (isOnboarding && ctxOnboardingState && ctxOnboardingActions) {
                const modelConfigsToUse =
                  (wellKnownLLMProvider ?? llmDescriptor)?.known_models ?? [];

                await submitOnboardingProvider({
                  providerName: VERTEXAI_PROVIDER_NAME,
                  payload: {
                    ...submitValues,
                    model_configurations: modelConfigsToUse,
                    is_auto_mode:
                      values.default_model_name === VERTEXAI_DEFAULT_MODEL,
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
                  providerName: VERTEXAI_PROVIDER_NAME,
                  values: submitValues,
                  initialValues,
                  modelConfigurations,
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
              <LLMConfigurationModalWrapper
                providerEndpoint={VERTEXAI_PROVIDER_NAME}
                existingProviderName={existingLlmProvider?.name}
                onClose={onClose}
                isFormValid={formikProps.isValid}
                isTesting={isTesting}
                testError={testError}
              >
                {!isOnboarding && (
                  <DisplayNameField disabled={!!existingLlmProvider} />
                )}

                <FileUploadFormField
                  name="custom_config.vertex_credentials"
                  label="Credentials File"
                  subtext="Upload your Google Cloud service account JSON credentials file."
                />

                <InputLayouts.Vertical
                  name="custom_config.vertex_location"
                  title="Location"
                  description="The Google Cloud region for your Vertex AI models (e.g., global, us-east1, us-central1, europe-west1)."
                  optional
                >
                  <InputTypeInField
                    name="custom_config.vertex_location"
                    placeholder={VERTEXAI_DEFAULT_LOCATION}
                  />
                </InputLayouts.Vertical>

                <Separator />

                {isOnboarding ? (
                  <SingleDefaultModelField placeholder="E.g. gemini-2.5-pro" />
                ) : (
                  <DisplayModels
                    modelConfigurations={modelConfigurations}
                    formikProps={formikProps}
                    recommendedDefaultModel={
                      wellKnownLLMProvider?.recommended_default_model ?? null
                    }
                    shouldShowAutoUpdateToggle={true}
                  />
                )}

                {!isOnboarding && <AdvancedOptions formikProps={formikProps} />}
              </LLMConfigurationModalWrapper>
            )}
          </Formik>
        );
      }}
    </ProviderFormEntrypointWrapper>
  );
}
