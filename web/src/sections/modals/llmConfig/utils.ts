import {
  LLMProviderView,
  ModelConfiguration,
  WellKnownLLMProviderDescriptor,
} from "@/interfaces/llm";
import * as Yup from "yup";
import { ScopedMutator } from "swr";
import { OnboardingActions, OnboardingState } from "@/interfaces/onboarding";

// Common class names for the Form component across all LLM provider forms
export const LLM_FORM_CLASS_NAME = "flex flex-col gap-y-4 items-stretch mt-6";

export const buildDefaultInitialValues = (
  existingLlmProvider?: LLMProviderView,
  modelConfigurations?: ModelConfiguration[],
  currentDefaultModelName?: string
) => {
  const defaultModelName =
    currentDefaultModelName ??
    existingLlmProvider?.model_configurations?.[0]?.name ??
    modelConfigurations?.[0]?.name ??
    "";

  // Auto mode must be explicitly enabled by the user
  // Default to false for new providers, preserve existing value when editing
  const isAutoMode = existingLlmProvider?.is_auto_mode ?? false;

  return {
    name: existingLlmProvider?.name || "",
    default_model_name: defaultModelName,
    is_public: existingLlmProvider?.is_public ?? true,
    is_auto_mode: isAutoMode,
    groups: existingLlmProvider?.groups ?? [],
    personas: existingLlmProvider?.personas ?? [],
    selected_model_names: existingLlmProvider
      ? existingLlmProvider.model_configurations
          .filter((modelConfiguration) => modelConfiguration.is_visible)
          .map((modelConfiguration) => modelConfiguration.name)
      : modelConfigurations
          ?.filter((modelConfiguration) => modelConfiguration.is_visible)
          .map((modelConfiguration) => modelConfiguration.name) ?? [],
  };
};

export const buildDefaultValidationSchema = () => {
  return Yup.object({
    name: Yup.string().required("Display Name is required"),
    default_model_name: Yup.string().required("Model name is required"),
    is_public: Yup.boolean().required(),
    is_auto_mode: Yup.boolean().required(),
    groups: Yup.array().of(Yup.number()),
    personas: Yup.array().of(Yup.number()),
    selected_model_names: Yup.array().of(Yup.string()),
  });
};

export const buildAvailableModelConfigurations = (
  existingLlmProvider?: LLMProviderView,
  wellKnownLLMProvider?: WellKnownLLMProviderDescriptor
): ModelConfiguration[] => {
  const existingModels = existingLlmProvider?.model_configurations ?? [];
  const wellKnownModels = wellKnownLLMProvider?.known_models ?? [];

  // Create a map to deduplicate by model name, preferring existing models
  const modelMap = new Map<string, ModelConfiguration>();

  // Add well-known models first
  wellKnownModels.forEach((model) => {
    modelMap.set(model.name, model);
  });

  // Override with existing models (they take precedence)
  existingModels.forEach((model) => {
    modelMap.set(model.name, model);
  });

  return Array.from(modelMap.values());
};

// Base form values that all provider forms share
export interface BaseLLMFormValues {
  name: string;
  api_key?: string;
  api_base?: string;
  default_model_name?: string;
  is_public: boolean;
  is_auto_mode: boolean;
  groups: number[];
  personas: number[];
  selected_model_names: string[];
  custom_config?: Record<string, string>;
}

export interface SubmitLLMProviderParams<
  T extends BaseLLMFormValues = BaseLLMFormValues,
> {
  providerName: string;
  values: T;
  initialValues: T;
  modelConfigurations: ModelConfiguration[];
  existingLlmProvider?: LLMProviderView;
  shouldMarkAsDefault?: boolean;
  hideSuccess?: boolean;
  setIsTesting: (testing: boolean) => void;
  mutate: ScopedMutator;
  onClose: () => void;
  setSubmitting: (submitting: boolean) => void;
}

export const filterModelConfigurations = (
  currentModelConfigurations: ModelConfiguration[],
  visibleModels: string[],
  defaultModelName?: string
): ModelConfiguration[] => {
  return currentModelConfigurations
    .map(
      (modelConfiguration): ModelConfiguration => ({
        name: modelConfiguration.name,
        is_visible: visibleModels.includes(modelConfiguration.name),
        max_input_tokens: modelConfiguration.max_input_tokens ?? null,
        supports_image_input: modelConfiguration.supports_image_input,
        supports_reasoning: modelConfiguration.supports_reasoning,
        display_name: modelConfiguration.display_name,
      })
    )
    .filter(
      (modelConfiguration) =>
        modelConfiguration.name === defaultModelName ||
        modelConfiguration.is_visible
    );
};

// Helper to get model configurations for auto mode
// In auto mode, we include ALL models but preserve their visibility status
// Models in the auto config are visible, others are created but not visible
export const getAutoModeModelConfigurations = (
  modelConfigurations: ModelConfiguration[]
): ModelConfiguration[] => {
  return modelConfigurations.map(
    (modelConfiguration): ModelConfiguration => ({
      name: modelConfiguration.name,
      is_visible: modelConfiguration.is_visible,
      max_input_tokens: modelConfiguration.max_input_tokens ?? null,
      supports_image_input: modelConfiguration.supports_image_input,
      supports_reasoning: modelConfiguration.supports_reasoning,
      display_name: modelConfiguration.display_name,
    })
  );
};

export type TestApiKeyResult =
  | { ok: true }
  | { ok: false; errorMessage: string };

export const getModelOptions = (
  fetchedModelConfigurations: Array<{ name: string }>
) => {
  return fetchedModelConfigurations.map((model) => ({
    label: model.name,
    value: model.name,
  }));
};

/** Initial values used by onboarding forms (flat shape, always creating new). */
export const buildOnboardingInitialValues = () => ({
  name: "",
  provider: "",
  api_key: "",
  api_base: "",
  api_version: "",
  default_model_name: "",
  model_configurations: [] as ModelConfiguration[],
  custom_config: {} as Record<string, string>,
  api_key_changed: true,
  groups: [] as number[],
  is_public: true,
  is_auto_mode: false,
  personas: [] as number[],
  selected_model_names: [] as string[],
  deployment_name: "",
  target_uri: "",
});

export interface SubmitOnboardingProviderParams {
  providerName: string;
  payload: Record<string, unknown>;
  onboardingState: OnboardingState;
  onboardingActions: OnboardingActions;
  isCustomProvider: boolean;
  onClose: () => void;
  setIsSubmitting: (submitting: boolean) => void;
}
