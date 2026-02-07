import { Form, Formik } from "formik";
import { LLMProviderFormProps } from "../interfaces";
import * as Yup from "yup";
import {
  ProviderFormEntrypointWrapper,
  ProviderFormContext,
} from "./components/FormWrapper";
import { DisplayNameField } from "./components/DisplayNameField";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import { FormActionButtons } from "./components/FormActionButtons";
import {
  buildDefaultInitialValues,
  buildDefaultValidationSchema,
  buildAvailableModelConfigurations,
  submitLLMProvider,
  LLM_FORM_CLASS_NAME,
} from "./formUtils";
import { AdvancedOptions } from "./components/AdvancedOptions";
import { DisplayModels } from "./components/DisplayModels";
import Separator from "@/refresh-components/Separator";
import InputWrapper from "./components/InputWrapper";

export const ANTHROPIC_PROVIDER_NAME = "anthropic";
const DEFAULT_DEFAULT_MODEL_NAME = "claude-sonnet-4-5";

export function AnthropicForm({
  existingLlmProvider,
  defaultLlmModel,
  shouldMarkAsDefault,
}: LLMProviderFormProps) {
  return (
    <ProviderFormEntrypointWrapper
      providerName="Anthropic"
      providerDisplayName={existingLlmProvider?.name ?? "Claude"}
      providerInternalName="anthropic"
      providerEndpoint={ANTHROPIC_PROVIDER_NAME}
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
          DEFAULT_DEFAULT_MODEL_NAME;

        const defaultModel = shouldMarkAsDefault
          ? isAutoMode
            ? autoModelDefault
            : defaultLlmModel?.model_name ?? DEFAULT_DEFAULT_MODEL_NAME
          : undefined;

        const initialValues = {
          ...buildDefaultInitialValues(
            existingLlmProvider,
            modelConfigurations,
            defaultModel
          ),
          api_key: existingLlmProvider?.api_key ?? "",
          api_base: existingLlmProvider?.api_base ?? "",
          // Default to auto mode for new Anthropic providers
          is_auto_mode: isAutoMode,
        };

        const validationSchema = buildDefaultValidationSchema().shape({
          api_key: Yup.string().required("API Key is required"),
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
                  providerName: ANTHROPIC_PROVIDER_NAME,
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
              {(formikProps) => {
                return (
                  <Form className={LLM_FORM_CLASS_NAME}>
                    <InputWrapper
                      label="API Key"
                      description="Paste your {link} from Anthropic to access your models."
                      descriptionLink={{
                        text: "API key",
                        href: "https://console.anthropic.com/dashboard",
                      }}
                    >
                      <PasswordInputTypeInField name="api_key" />
                    </InputWrapper>

                    <Separator noPadding />

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
