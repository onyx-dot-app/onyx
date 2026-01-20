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

export const AGENT_GATEWAY_PROVIDER_NAME = "agent_gateway";
const DEFAULT_API_BASE = "http://52.147.214.252:8080/gemini";

// Default models available through AgentGateway
const AGENT_GATEWAY_MODELS: ModelConfiguration[] = [
  {
    name: "gemini-2.5-flash",
    is_visible: true,
    max_input_tokens: 1000000,
    supports_image_input: true,
  },
  {
    name: "gemini-2.5-pro",
    is_visible: true,
    max_input_tokens: 2000000,
    supports_image_input: true,
  },
];

interface AgentGatewayFormValues extends BaseLLMFormValues {
  api_base: string;
}

interface AgentGatewayFormContentProps {
  formikProps: FormikProps<AgentGatewayFormValues>;
  existingLlmProvider?: LLMProviderView;
  isTesting: boolean;
  testError: string;
  mutate: () => void;
  onClose: () => void;
  isFormValid: boolean;
  modelConfigurations: ModelConfiguration[];
}

function AgentGatewayFormContent({
  formikProps,
  existingLlmProvider,
  isTesting,
  testError,
  mutate,
  onClose,
  isFormValid,
  modelConfigurations,
}: AgentGatewayFormContentProps) {
  return (
    <Form className={LLM_FORM_CLASS_NAME}>
      <DisplayNameField disabled={!!existingLlmProvider} />

      <TextFormField
        name="api_base"
        label="API Base URL"
        subtext="The base URL for your AgentGateway endpoint (e.g., http://52.147.214.252:8080/gemini)"
        placeholder={DEFAULT_API_BASE}
      />

      <DisplayModels
        modelConfigurations={modelConfigurations}
        formikProps={formikProps}
        noModelConfigurationsMessage="No models configured."
        isLoading={false}
        recommendedDefaultModel={{ name: "gemini-2.5-flash", display_name: "Gemini 2.5 Flash" }}
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

export function AgentGatewayForm({
  existingLlmProvider,
  shouldMarkAsDefault,
}: LLMProviderFormProps) {
  return (
    <ProviderFormEntrypointWrapper
      providerName="AgentGateway"
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
        // Use existing model configurations or fall back to defaults
        const modelConfigurations =
          existingLlmProvider?.model_configurations?.length
            ? existingLlmProvider.model_configurations
            : wellKnownLLMProvider?.known_models?.length
              ? wellKnownLLMProvider.known_models
              : AGENT_GATEWAY_MODELS;

        const initialValues: AgentGatewayFormValues = {
          ...buildDefaultInitialValues(
            existingLlmProvider,
            modelConfigurations
          ),
          api_base: existingLlmProvider?.api_base ?? DEFAULT_API_BASE,
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
                await submitLLMProvider({
                  providerName: AGENT_GATEWAY_PROVIDER_NAME,
                  values,
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
                <AgentGatewayFormContent
                  formikProps={formikProps}
                  existingLlmProvider={existingLlmProvider}
                  isTesting={isTesting}
                  testError={testError}
                  mutate={mutate}
                  onClose={onClose}
                  isFormValid={formikProps.isValid}
                  modelConfigurations={modelConfigurations}
                />
              )}
            </Formik>
          </>
        );
      }}
    </ProviderFormEntrypointWrapper>
  );
}
