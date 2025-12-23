import { LoadingAnimation } from "@/components/Loading";
import Separator from "@/refresh-components/Separator";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { Form, Formik, FormikProps } from "formik";
import { SelectorFormField, TextFormField } from "@/components/Field";
import { useEffect, useRef, useState } from "react";
import { LLMProviderView, ModelConfiguration } from "../interfaces";
import { dynamicProviderConfigs, fetchModels } from "../utils";
import { PopupSpec } from "@/components/admin/connectors/Popup";
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
  submitLLMProvider,
  BaseLLMFormValues,
} from "./formUtils";
import { AdvancedOptions } from "./components/AdvancedOptions";

export const ANTHROPIC_PROVIDER_NAME = "anthropic";
const DEFAULT_DEFAULT_MODEL_NAME = "claude-sonnet-4-5";

interface AnthropicFormProps {
  existingLlmProvider?: LLMProviderView;
  shouldMarkAsDefault?: boolean;
}

export function AnthropicForm({
  existingLlmProvider,
  shouldMarkAsDefault,
}: AnthropicFormProps) {
  return (
    <ProviderFormEntrypointWrapper
      providerName="Anthropic"
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
        modelConfigurations,
      }: ProviderFormContext) => {
        const initialValues = {
          ...buildDefaultInitialValues(
            existingLlmProvider,
            modelConfigurations
          ),
          api_key: existingLlmProvider?.api_key ?? "",
          api_base: existingLlmProvider?.api_base ?? "",
          default_model_name: DEFAULT_DEFAULT_MODEL_NAME,
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
                  <Form className="gap-y-4 items-stretch mt-6">
                    <DisplayNameField disabled={!!existingLlmProvider} />

                    <ApiKeyField />

                    <Separator />

                    <SelectorFormField
                      name="default_model_name"
                      subtext="The model to use by default for this provider unless otherwise specified."
                      label="Default Model"
                      options={modelConfigurations.map(
                        (modelConfiguration) => ({
                          name: modelConfiguration.name,
                          value: modelConfiguration.name,
                        })
                      )}
                      maxHeight="max-h-56"
                    />

                    <Separator />

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
