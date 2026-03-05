import Separator from "@/refresh-components/Separator";
import { Form, Formik } from "formik";
import { TextFormField } from "@/components/Field";
import {
  LLMProviderFormProps,
  ModelConfiguration,
  OpenRouterModelResponse,
} from "@/interfaces/llm";
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
  submitOnboardingProvider,
  buildOnboardingInitialValues,
  BaseLLMFormValues,
  LLM_FORM_CLASS_NAME,
} from "./formUtils";
import { AdvancedOptions } from "./components/AdvancedOptions";
import { DisplayModels } from "./components/DisplayModels";
import { SingleDefaultModelField } from "./components/SingleDefaultModelField";
import { FetchModelsButton } from "./components/FetchModelsButton";
import { useState } from "react";

export const OPENROUTER_PROVIDER_NAME = "openrouter";
const OPENROUTER_DISPLAY_NAME = "OpenRouter";
const DEFAULT_API_BASE = "https://openrouter.ai/api/v1";
const OPENROUTER_MODELS_API_URL = "/api/admin/llm/openrouter/available-models";

interface OpenRouterModalValues extends BaseLLMFormValues {
  api_key: string;
  api_base: string;
}

async function fetchOpenRouterModels(params: {
  apiBase: string;
  apiKey: string;
  providerName?: string;
}): Promise<{ models: ModelConfiguration[]; error?: string }> {
  if (!params.apiBase || !params.apiKey) {
    return {
      models: [],
      error: "API Base and API Key are required to fetch models",
    };
  }

  try {
    const response = await fetch(OPENROUTER_MODELS_API_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        api_base: params.apiBase,
        api_key: params.apiKey,
        provider_name: params.providerName,
      }),
    });

    if (!response.ok) {
      let errorMessage = "Failed to fetch models";
      try {
        const errorData = await response.json();
        errorMessage = errorData.detail || errorMessage;
      } catch {
        // ignore JSON parsing errors
      }
      return { models: [], error: errorMessage };
    }

    const data: OpenRouterModelResponse[] = await response.json();
    const models: ModelConfiguration[] = data.map((modelData) => ({
      name: modelData.name,
      display_name: modelData.display_name,
      is_visible: true,
      max_input_tokens: modelData.max_input_tokens,
      supports_image_input: modelData.supports_image_input,
      supports_reasoning: false,
    }));

    return { models };
  } catch (error) {
    const errorMessage =
      error instanceof Error ? error.message : "Unknown error";
    return { models: [], error: errorMessage };
  }
}

export function OpenRouterModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  open,
  onOpenChange,
  onboardingState,
  onboardingActions,
  llmDescriptor,
}: LLMProviderFormProps) {
  const [fetchedModels, setFetchedModels] = useState<ModelConfiguration[]>([]);
  const isOnboarding = variant === "onboarding";

  return (
    <ProviderFormEntrypointWrapper
      providerName={OPENROUTER_DISPLAY_NAME}
      providerEndpoint={OPENROUTER_PROVIDER_NAME}
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

        const initialValues: OpenRouterModalValues = isOnboarding
          ? ({
              ...buildOnboardingInitialValues(),
              name: OPENROUTER_PROVIDER_NAME,
              provider: OPENROUTER_PROVIDER_NAME,
              api_key: "",
              api_base: DEFAULT_API_BASE,
              default_model_name: "",
            } as OpenRouterModalValues)
          : {
              ...buildDefaultInitialValues(
                existingLlmProvider,
                modelConfigurations
              ),
              api_key: existingLlmProvider?.api_key ?? "",
              api_base: existingLlmProvider?.api_base ?? DEFAULT_API_BASE,
            };

        const validationSchema = isOnboarding
          ? Yup.object().shape({
              api_key: Yup.string().required("API Key is required"),
              api_base: Yup.string().required("API Base URL is required"),
              default_model_name: Yup.string().required(
                "Model name is required"
              ),
            })
          : buildDefaultValidationSchema().shape({
              api_key: Yup.string().required("API Key is required"),
              api_base: Yup.string().required("API Base URL is required"),
            });

        return (
          <Formik
            initialValues={initialValues}
            validationSchema={validationSchema}
            validateOnMount={true}
            onSubmit={async (values, { setSubmitting }) => {
              if (isOnboarding && ctxOnboardingState && ctxOnboardingActions) {
                const modelConfigsToUse =
                  fetchedModels.length > 0 ? fetchedModels : [];

                await submitOnboardingProvider({
                  providerName: OPENROUTER_PROVIDER_NAME,
                  payload: {
                    ...values,
                    model_configurations: modelConfigsToUse,
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
                  providerName: OPENROUTER_PROVIDER_NAME,
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
              }
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
                  {!isOnboarding && (
                    <DisplayNameField disabled={!!existingLlmProvider} />
                  )}

                  <PasswordInputTypeInField name="api_key" label="API Key" />

                  <TextFormField
                    name="api_base"
                    label="API Base URL"
                    subtext="The base URL for OpenRouter API."
                    placeholder={DEFAULT_API_BASE}
                  />

                  <FetchModelsButton
                    onFetch={() =>
                      fetchOpenRouterModels({
                        apiBase: formikProps.values.api_base,
                        apiKey: formikProps.values.api_key,
                        providerName: existingLlmProvider?.name,
                      })
                    }
                    isDisabled={isFetchDisabled}
                    disabledHint={
                      !formikProps.values.api_key
                        ? "Enter your API key first."
                        : !formikProps.values.api_base
                          ? "Enter the API base URL."
                          : undefined
                    }
                    onModelsFetched={setFetchedModels}
                    autoFetchOnInitialLoad={!!existingLlmProvider}
                  />

                  <Separator />

                  {isOnboarding ? (
                    <SingleDefaultModelField placeholder="E.g. openai/gpt-4o" />
                  ) : (
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
                  )}

                  {!isOnboarding && (
                    <AdvancedOptions formikProps={formikProps} />
                  )}

                  <FormActionButtons
                    isTesting={isTesting}
                    testError={testError}
                    existingLlmProvider={
                      isOnboarding ? undefined : existingLlmProvider
                    }
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
