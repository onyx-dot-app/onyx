import Separator from "@/refresh-components/Separator";
import { Form, Formik } from "formik";
import { TextFormField } from "@/components/Field";
import {
  LLMProviderFormProps,
  LLMProviderName,
  ModelConfiguration,
} from "@/interfaces/llm";
import { fetchLiteLLMProxyModels } from "@/app/admin/configuration/llm/utils";
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
  BaseLLMFormValues,
  LLM_FORM_CLASS_NAME,
} from "./formUtils";
import { AdvancedOptions } from "./components/AdvancedOptions";
import { DisplayModels } from "./components/DisplayModels";
import { FetchModelsButton } from "./components/FetchModelsButton";
import { useState } from "react";

const LITELLM_PROXY_DISPLAY_NAME = "LiteLLM Proxy";
const DEFAULT_API_BASE = "http://localhost:4000";

interface LiteLLMProxyModalValues extends BaseLLMFormValues {
  api_key: string;
  api_base: string;
}

export function LiteLLMProxyModal({
  existingLlmProvider,
  shouldMarkAsDefault,
  open,
  onOpenChange,
}: LLMProviderFormProps) {
  const [fetchedModels, setFetchedModels] = useState<ModelConfiguration[]>([]);

  return (
    <ProviderFormEntrypointWrapper
      providerName={LITELLM_PROXY_DISPLAY_NAME}
      providerEndpoint={LLMProviderName.LITELLM_PROXY}
      existingLlmProvider={existingLlmProvider}
      open={open}
      onOpenChange={onOpenChange}
    >
      {({
        onClose,
        mutate,
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
        const initialValues: LiteLLMProxyModalValues = {
          ...buildDefaultInitialValues(
            existingLlmProvider,
            modelConfigurations
          ),
          api_key: existingLlmProvider?.api_key ?? "",
          api_base: existingLlmProvider?.api_base ?? DEFAULT_API_BASE,
        };

        const validationSchema = buildDefaultValidationSchema().shape({
          api_key: Yup.string().required("API Key is required"),
          api_base: Yup.string().required("API Base URL is required"),
        });

        return (
          <Formik
            initialValues={initialValues}
            validationSchema={validationSchema}
            validateOnMount={true}
            onSubmit={async (values, { setSubmitting }) => {
              await submitLLMProvider({
                providerName: LLMProviderName.LITELLM_PROXY,
                values,
                initialValues,
                modelConfigurations:
                  fetchedModels.length > 0
                    ? fetchedModels
                    : modelConfigurations,
                existingLlmProvider,
                shouldMarkAsDefault,
                setIsTesting,
                setTestError,
                mutate,
                onClose,
                setSubmitting,
              });
            }}
          >
            {(formikProps) => {
              const currentModels =
                fetchedModels.length > 0
                  ? fetchedModels
                  : existingLlmProvider?.model_configurations ||
                    modelConfigurations;

              const isFetchDisabled =
                !formikProps.values.api_base || !formikProps.values.api_key;

              return (
                <Form className={LLM_FORM_CLASS_NAME}>
                  <DisplayNameField disabled={!!existingLlmProvider} />

                  <TextFormField
                    name="api_base"
                    label="API Base URL"
                    subtext="The base URL for your LiteLLM Proxy server (e.g., http://localhost:4000)"
                    placeholder={DEFAULT_API_BASE}
                  />

                  <PasswordInputTypeInField name="api_key" label="API Key" />

                  <FetchModelsButton
                    onFetch={() =>
                      fetchLiteLLMProxyModels({
                        api_base: formikProps.values.api_base,
                        api_key: formikProps.values.api_key,
                      })
                    }
                    isDisabled={isFetchDisabled}
                    disabledHint={
                      !formikProps.values.api_base
                        ? "Enter the API base URL first."
                        : !formikProps.values.api_key
                          ? "Enter your API key first."
                          : undefined
                    }
                    onModelsFetched={setFetchedModels}
                    autoFetchOnInitialLoad={!!existingLlmProvider}
                  />

                  <Separator />

                  <DisplayModels
                    modelConfigurations={currentModels}
                    formikProps={formikProps}
                    noModelConfigurationsMessage={
                      "Fetch available models first, then you'll be able to select " +
                      "the models you want to make available in Onyx."
                    }
                    recommendedDefaultModel={null}
                    shouldShowAutoUpdateToggle={false}
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
        );
      }}
    </ProviderFormEntrypointWrapper>
  );
}
