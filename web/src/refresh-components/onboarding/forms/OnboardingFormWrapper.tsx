import React, {
  useState,
  useMemo,
  ReactNode,
  createContext,
  useContext,
} from "react";
import { Form, Formik, FormikProps } from "formik";
import * as Yup from "yup";
import ProviderModal from "@/components/modals/ProviderModal";
import {
  ModelConfiguration,
  WellKnownLLMProviderDescriptor,
} from "@/app/admin/configuration/llm/interfaces";
import { LLM_PROVIDERS_ADMIN_URL } from "@/app/admin/configuration/llm/constants";
import { OnboardingActions, OnboardingState } from "../types";
import { APIFormFieldState } from "@/refresh-components/form/types";
import {
  testApiKeyHelper,
  testCustomProvider,
  getModelOptions,
} from "../components/llmConnectionHelpers";
import {
  canProviderFetchModels,
  fetchModels,
} from "@/app/admin/configuration/llm/utils";
import type { IconProps } from "@opal/types";
import { ComboBoxOption } from "@/refresh-components/inputs/InputComboBox";

export interface OnboardingFormContextType {
  // API status tracking
  apiStatus: APIFormFieldState;
  setApiStatus: (status: APIFormFieldState) => void;
  showApiMessage: boolean;
  setShowApiMessage: (show: boolean) => void;
  errorMessage: string;
  setErrorMessage: (message: string) => void;

  // Models status tracking
  modelsApiStatus: APIFormFieldState;
  setModelsApiStatus: (status: APIFormFieldState) => void;
  showModelsApiErrorMessage: boolean;
  setShowModelsApiErrorMessage: (show: boolean) => void;
  modelsErrorMessage: string;
  setModelsErrorMessage: (message: string) => void;

  // Model fetching
  isFetchingModels: boolean;
  fetchedModelConfigurations: ModelConfiguration[];
  modelOptions: ComboBoxOption[];
  canFetchModels: boolean;
  handleFetchModels: () => Promise<void>;

  // Provider info
  llmDescriptor?: WellKnownLLMProviderDescriptor;
  isCustomProvider: boolean;

  // Submission
  isSubmitting: boolean;

  // Disabled state
  disabled: boolean;
}

const OnboardingFormContext = createContext<OnboardingFormContextType | null>(
  null
);

export function useOnboardingFormContext(): OnboardingFormContextType {
  const context = useContext(OnboardingFormContext);
  if (!context) {
    throw new Error(
      "useOnboardingFormContext must be used within OnboardingFormWrapper"
    );
  }
  return context;
}

export interface OnboardingFormWrapperProps<T extends Record<string, any>> {
  // Modal props
  icon: React.FunctionComponent<IconProps>;
  title: string;
  description?: string;

  // Provider info
  llmDescriptor?: WellKnownLLMProviderDescriptor;
  isCustomProvider?: boolean;

  // Onboarding integration
  onboardingState: OnboardingState;
  onboardingActions: OnboardingActions;

  // Modal control
  open: boolean;
  onOpenChange: (open: boolean) => void;

  // Form configuration
  initialValues: T;
  validationSchema: Yup.Schema<any>;

  // Render function for form content
  children: (formikProps: FormikProps<T>) => ReactNode;

  // Optional: transform values before submission
  transformValues?: (values: T, fetchedModelConfigurations: any[]) => any;
}

export function OnboardingFormWrapper<T extends Record<string, any>>({
  icon,
  title,
  description,
  llmDescriptor,
  isCustomProvider = false,
  onboardingState,
  onboardingActions,
  open,
  onOpenChange,
  initialValues,
  validationSchema,
  children,
  transformValues,
}: OnboardingFormWrapperProps<T>) {
  // API status state
  const [apiStatus, setApiStatus] = useState<APIFormFieldState>("loading");
  const [showApiMessage, setShowApiMessage] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  // Models status state
  const [modelsApiStatus, setModelsApiStatus] =
    useState<APIFormFieldState>("loading");
  const [showModelsApiErrorMessage, setShowModelsApiErrorMessage] =
    useState(false);
  const [modelsErrorMessage, setModelsErrorMessage] = useState("");

  // Model fetching state
  const [isFetchingModels, setIsFetchingModels] = useState(false);
  const [fetchedModelConfigurations, setFetchedModelConfigurations] = useState<
    any[]
  >([]);

  // Submission state
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Form reset key for re-initialization
  const [formResetKey, setFormResetKey] = useState(0);

  // Compute model options
  const modelOptions = useMemo(
    () => getModelOptions(fetchedModelConfigurations),
    [fetchedModelConfigurations]
  );

  // Check if provider can fetch models
  const canFetchModels = useMemo(
    () => canProviderFetchModels(llmDescriptor?.name),
    [llmDescriptor]
  );

  // Reset form when modal opens
  React.useEffect(() => {
    if (open) {
      setFormResetKey((prev) => prev + 1);
      setApiStatus("loading");
      setShowApiMessage(false);
      setErrorMessage("");
      setModelsApiStatus("loading");
      setShowModelsApiErrorMessage(false);
      setModelsErrorMessage("");
      setFetchedModelConfigurations([]);
    }
  }, [open]);

  // Update models API status when configurations change
  React.useEffect(() => {
    if (fetchedModelConfigurations.length > 0 && !isFetchingModels) {
      setModelsApiStatus("success");
    }
  }, [fetchedModelConfigurations, isFetchingModels]);

  const handleSubmit = async (values: T) => {
    setIsSubmitting(true);

    // Use fetched model configurations if available
    let modelConfigsToUse =
      fetchedModelConfigurations.length > 0
        ? fetchedModelConfigurations
        : llmDescriptor?.model_configurations.map((model) => ({
            name: model.name,
            is_visible: true,
            max_input_tokens: model.max_input_tokens,
            supports_image_input: model.supports_image_input,
          })) ?? [];

    // Transform values if transformer provided
    const payload = transformValues
      ? transformValues(values, modelConfigsToUse)
      : {
          ...initialValues,
          ...values,
          model_configurations: modelConfigsToUse,
        };

    // Test the configuration first
    setApiStatus("loading");
    setShowApiMessage(true);

    let result;
    if (llmDescriptor) {
      result = await testApiKeyHelper(llmDescriptor.name, payload);
    } else {
      result = await testCustomProvider(payload);
    }

    if (!result.ok) {
      setErrorMessage(result.errorMessage);
      setApiStatus("error");
      setIsSubmitting(false);
      return;
    }
    setApiStatus("success");

    // Create the provider
    const response = await fetch(
      `${LLM_PROVIDERS_ADMIN_URL}?is_creation=true`,
      {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      }
    );

    if (!response.ok) {
      const errorMsg = (await response.json()).detail;
      console.error("Failed to create LLM provider", errorMsg);
      setErrorMessage(errorMsg);
      setApiStatus("error");
      setIsSubmitting(false);
      return;
    }

    // If this is the first LLM provider, set it as the default
    if (
      onboardingState?.data?.llmProviders == null ||
      onboardingState.data.llmProviders.length === 0
    ) {
      try {
        const newLlmProvider = await response.json();
        if (newLlmProvider?.id != null) {
          const setDefaultResponse = await fetch(
            `${LLM_PROVIDERS_ADMIN_URL}/${newLlmProvider.id}/default`,
            { method: "POST" }
          );
          if (!setDefaultResponse.ok) {
            const err = await setDefaultResponse.json().catch(() => ({}));
            console.error("Failed to set provider as default", err?.detail);
          }
        }
      } catch (_e) {
        console.error("Failed to set new provider as default", _e);
      }
    }

    // Update onboarding state
    onboardingActions?.updateData({
      llmProviders: [
        ...(onboardingState?.data.llmProviders ?? []),
        isCustomProvider ? "custom" : llmDescriptor?.name ?? "",
      ],
    });
    onboardingActions?.setButtonActive(true);

    setIsSubmitting(false);
    onOpenChange(false);
  };

  // Create context value with formik-dependent fetch function
  const createContextValue = (
    formikProps: FormikProps<T>
  ): OnboardingFormContextType => ({
    apiStatus,
    setApiStatus,
    showApiMessage,
    setShowApiMessage,
    errorMessage,
    setErrorMessage,
    modelsApiStatus,
    setModelsApiStatus,
    showModelsApiErrorMessage,
    setShowModelsApiErrorMessage,
    modelsErrorMessage,
    setModelsErrorMessage,
    isFetchingModels,
    fetchedModelConfigurations,
    modelOptions,
    canFetchModels,
    handleFetchModels: async () => {
      if (!llmDescriptor) return;

      setIsFetchingModels(true);
      try {
        const { models, error } = await fetchModels(
          llmDescriptor.name,
          formikProps.values as Record<string, any>
        );
        if (error) {
          setModelsApiStatus("error");
          setShowModelsApiErrorMessage(true);
          setModelsErrorMessage(error);
        } else {
          setFetchedModelConfigurations(models);
          // Set default model to first available model if not set
          if (models.length > 0 && !formikProps.values.default_model_name) {
            formikProps.setFieldValue(
              "default_model_name",
              models[0]?.name ?? ""
            );
          }
        }
      } finally {
        setIsFetchingModels(false);
      }
    },
    llmDescriptor,
    isCustomProvider,
    isSubmitting,
    disabled: isSubmitting,
  });

  return (
    <Formik<T>
      key={formResetKey}
      initialValues={initialValues}
      validationSchema={validationSchema}
      enableReinitialize
      onSubmit={handleSubmit}
    >
      {(formikProps) => {
        const contextValue = createContextValue(formikProps);

        return (
          <OnboardingFormContext.Provider value={contextValue}>
            <ProviderModal
              open={open}
              onOpenChange={onOpenChange}
              title={title}
              description={description}
              icon={icon}
              onSubmit={formikProps.submitForm}
              submitDisabled={formikProps.isValid || !formikProps.dirty}
              isSubmitting={isSubmitting}
            >
              <Form className="flex flex-col gap-0">
                <div className="flex flex-col p-4 gap-4 bg-background-tint-01 w-full">
                  {children(formikProps)}
                </div>
              </Form>
            </ProviderModal>
          </OnboardingFormContext.Provider>
        );
      }}
    </Formik>
  );
}
