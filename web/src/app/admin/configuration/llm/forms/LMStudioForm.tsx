import { Form, Formik, FormikProps } from "formik";
import { TextFormField } from "@/components/Field";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
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
import { useEffect, useRef, useState } from "react";
import { fetchLMStudioModels } from "../utils";

export const LM_STUDIO_PROVIDER_NAME = "lm_studio";
const DEFAULT_API_BASE = "http://localhost:1234/v1";

interface LMStudioFormValues extends BaseLLMFormValues {
  api_base: string;
  custom_config: {
    LM_STUDIO_API_KEY?: string;
  };
}

interface LMStudioFormContentProps {
  formikProps: FormikProps<LMStudioFormValues>;
  existingLlmProvider?: LLMProviderView;
  fetchedModels: ModelConfiguration[];
  setFetchedModels: (models: ModelConfiguration[]) => void;
  isTesting: boolean;
  testError: string;
  mutate: () => void;
  onClose: () => void;
  isFormValid: boolean;
}

function LMStudioFormContent({
  formikProps,
  existingLlmProvider,
  fetchedModels,
  setFetchedModels,
  isTesting,
  testError,
  mutate,
  onClose,
  isFormValid,
}: LMStudioFormContentProps) {
  const [isLoadingModels, setIsLoadingModels] = useState(true);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!formikProps.values.api_base) return;

    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }

    debounceRef.current = setTimeout(() => {
      setIsLoadingModels(true);
      fetchLMStudioModels({
        api_base: formikProps.values.api_base,
        api_key: formikProps.values.custom_config?.LM_STUDIO_API_KEY,
        provider_name: existingLlmProvider?.name,
      })
        .then((data) => {
          if (data.error) {
            console.error("Error fetching models:", data.error);
            setFetchedModels([]);
            return;
          }
          setFetchedModels(data.models);
        })
        .finally(() => {
          setIsLoadingModels(false);
        });
    }, 500);

    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
    };
  }, [
    formikProps.values.api_base,
    formikProps.values.custom_config?.LM_STUDIO_API_KEY,
    existingLlmProvider?.name,
    setFetchedModels,
  ]);

  const currentModels =
    fetchedModels.length > 0
      ? fetchedModels
      : existingLlmProvider?.model_configurations || [];

  return (
    <Form className={LLM_FORM_CLASS_NAME}>
      <DisplayNameField disabled={!!existingLlmProvider} />

      <TextFormField
        name="api_base"
        label="API Base URL"
        subtext="The base URL for your LM Studio server (e.g., http://localhost:1234/v1)"
        placeholder={DEFAULT_API_BASE}
      />

      <PasswordInputTypeInField
        name="custom_config.LM_STUDIO_API_KEY"
        label="API Key (Optional)"
        subtext="Optional API key if your LM Studio server requires authentication."
      />

      <DisplayModels
        modelConfigurations={currentModels}
        formikProps={formikProps}
        noModelConfigurationsMessage="No models found. Please provide a valid API base URL and ensure LM Studio is running."
        isLoading={isLoadingModels}
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
        isFormValid={isFormValid}
      />
    </Form>
  );
}

export function LMStudioForm({
  existingLlmProvider,
  shouldMarkAsDefault,
}: LLMProviderFormProps) {
  const [fetchedModels, setFetchedModels] = useState<ModelConfiguration[]>([]);

  return (
    <ProviderFormEntrypointWrapper
      providerName="LM Studio"
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
        const initialValues: LMStudioFormValues = {
          ...buildDefaultInitialValues(
            existingLlmProvider,
            modelConfigurations
          ),
          api_base: existingLlmProvider?.api_base ?? DEFAULT_API_BASE,
          custom_config: {
            LM_STUDIO_API_KEY:
              (existingLlmProvider?.custom_config
                ?.LM_STUDIO_API_KEY as string) ?? "",
          },
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
                // Filter out empty custom_config values
                const filteredCustomConfig = Object.fromEntries(
                  Object.entries(values.custom_config || {}).filter(
                    ([, v]) => v !== ""
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
                  providerName: LM_STUDIO_PROVIDER_NAME,
                  values: submitValues,
                  initialValues,
                  modelConfigurations:
                    fetchedModels.length > 0
                      ? fetchedModels
                      : modelConfigurations,
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
                <LMStudioFormContent
                  formikProps={formikProps}
                  existingLlmProvider={existingLlmProvider}
                  fetchedModels={fetchedModels}
                  setFetchedModels={setFetchedModels}
                  isTesting={isTesting}
                  testError={testError}
                  mutate={mutate}
                  onClose={onClose}
                  isFormValid={formikProps.isValid}
                />
              )}
            </Formik>
          </>
        );
      }}
    </ProviderFormEntrypointWrapper>
  );
}
