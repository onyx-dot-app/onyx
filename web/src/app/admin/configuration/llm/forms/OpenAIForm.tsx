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
import { ProviderIcon } from "../ProviderIcon";
import Separator from "@/refresh-components/Separator";

export const OPENAI_PROVIDER_NAME = "openai";

export function OpenAIForm({
  existingLlmProvider,
  defaultLlmModel,
  shouldMarkAsDefault,
}: LLMProviderFormProps) {
  return (
    <ProviderFormEntrypointWrapper
      providerName="OpenAI"
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
        const initialValues = {
          ...buildDefaultInitialValues(
            existingLlmProvider,
            modelConfigurations
          ),
          api_key: existingLlmProvider?.api_key ?? "",
          is_auto_mode: existingLlmProvider?.is_auto_mode ?? true,
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
                    <PasswordInputTypeInField
                      name="api_key"
                      label="API Key"
                      subtext="Paste your API key from OpenAI to access your models."
                    />

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
