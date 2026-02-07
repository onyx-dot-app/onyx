import { Form, Formik } from "formik";
import * as Yup from "yup";

import { LLMProviderFormProps } from "../interfaces";
import { ProviderFormEntrypointWrapper } from "./components/FormWrapper";
import { DisplayNameField } from "./components/DisplayNameField";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import {
  buildDefaultInitialValues,
  buildDefaultValidationSchema,
  buildAvailableModelConfigurations,
  submitLLMProvider,
} from "./formUtils";
import { AdvancedOptions } from "./components/AdvancedOptions";
import { DisplayModels } from "./components/DisplayModels";
import LLMFormLayout from "./components/FormLayout";
import Separator from "@/refresh-components/Separator";
import InputWrapper from "./components/InputWrapper";

export const OPENAI_PROVIDER_NAME = "openai";
const DEFAULT_DEFAULT_MODEL_NAME = "gpt-5.2";

export function OpenAIForm({
  existingLlmProvider,
  defaultLlmModel,
  shouldMarkAsDefault,
}: LLMProviderFormProps) {
  return (
    <ProviderFormEntrypointWrapper
      providerName="OpenAI"
      providerDisplayName={existingLlmProvider?.name ?? "OpenAI"}
      providerEndpoint={OPENAI_PROVIDER_NAME}
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
      }) => {
        const modelConfigurations = buildAvailableModelConfigurations(
          existingLlmProvider,
          wellKnownLLMProvider
        );
        const isAutoMode = existingLlmProvider?.is_auto_mode ?? true;
        const autoModelDefault =
          wellKnownLLMProvider?.recommended_default_model?.name ??
          DEFAULT_DEFAULT_MODEL_NAME;

        // We use a default model if we're editting and this provider is the global default
        // Or we are creating the first provider (and shouldMarkAsDefault is true)
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
                  providerName: OPENAI_PROVIDER_NAME,
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
                <Form>
                  <LLMFormLayout.Body>
                    <InputWrapper
                      label="API Key"
                      description="Paste your {link} from OpenAI to access your models."
                      descriptionLink={{
                        text: "API key",
                        href: "https://platform.openai.com/api-keys",
                      }}
                    >
                      <PasswordInputTypeInField
                        name="api_key"
                        subtext="Paste your API key from OpenAI to access your models."
                      />
                    </InputWrapper>

                    <Separator />

                    <DisplayNameField disabled={!!existingLlmProvider} />

                    <Separator />

                    <DisplayModels
                      modelConfigurations={modelConfigurations}
                      formikProps={formikProps}
                      shouldShowAutoUpdateToggle={true}
                    />

                    <AdvancedOptions formikProps={formikProps} />
                  </LLMFormLayout.Body>

                  <LLMFormLayout.Footer
                    onCancel={onClose}
                    submitLabel={existingLlmProvider ? "Update" : "Enable"}
                    isSubmitting={isTesting}
                    isSubmitDisabled={!formikProps.isValid}
                    error={testError}
                  />
                </Form>
              )}
            </Formik>
          </>
        );
      }}
    </ProviderFormEntrypointWrapper>
  );
}
