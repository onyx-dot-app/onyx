import {
  LLMProviderView,
  ModelConfiguration,
  WellKnownLLMProviderDescriptor,
} from "../interfaces";
import { LLM_PROVIDERS_ADMIN_URL } from "../constants";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import * as Yup from "yup";
import isEqual from "lodash/isEqual";

// Common class names for the Form component across all LLM provider forms
export const LLM_FORM_CLASS_NAME = "flex flex-col gap-y-4 items-stretch mt-6";

export const buildDefaultInitialValues = (
  existingLlmProvider?: LLMProviderView,
  modelConfigurations?: ModelConfiguration[]
) => {
  const defaultModelName =
    existingLlmProvider?.default_model_name ??
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
  setTestError: (error: string) => void;
  setPopup?: (popup: PopupSpec) => void;
  mutate: (key: string) => void;
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
export const getAutoModeModelConfigurations = (
  modelConfigurations: ModelConfiguration[]
): ModelConfiguration[] => {
  return modelConfigurations
    .filter((m) => m.is_visible)
    .map(
      (modelConfiguration): ModelConfiguration => ({
        name: modelConfiguration.name,
        is_visible: true,
        max_input_tokens: modelConfiguration.max_input_tokens ?? null,
        supports_image_input: modelConfiguration.supports_image_input,
        display_name: modelConfiguration.display_name,
      })
    );
};

export const submitLLMProvider = async <T extends BaseLLMFormValues>({
  providerName,
  values,
  initialValues,
  modelConfigurations,
  existingLlmProvider,
  shouldMarkAsDefault,
  hideSuccess,
  setIsTesting,
  setTestError,
  setPopup,
  mutate,
  onClose,
  setSubmitting,
}: SubmitLLMProviderParams<T>): Promise<void> => {
  setSubmitting(true);

  const { selected_model_names: visibleModels, api_key, ...rest } = values;

  // In auto mode, use recommended models from descriptor
  // In manual mode, use user's selection
  let filteredModelConfigurations: ModelConfiguration[];
  let finalDefaultModelName = rest.default_model_name;

  if (values.is_auto_mode) {
    filteredModelConfigurations =
      getAutoModeModelConfigurations(modelConfigurations);

    // In auto mode, use the first recommended model as default if current default isn't in the list
    const visibleModelNames = new Set(
      filteredModelConfigurations.map((m) => m.name)
    );
    if (
      finalDefaultModelName &&
      !visibleModelNames.has(finalDefaultModelName)
    ) {
      finalDefaultModelName = filteredModelConfigurations[0]?.name ?? "";
    }
  } else {
    filteredModelConfigurations = filterModelConfigurations(
      modelConfigurations,
      visibleModels,
      rest.default_model_name as string | undefined
    );
  }

  const finalValues = {
    ...rest,
    default_model_name: finalDefaultModelName,
    api_key,
    api_key_changed: api_key !== (initialValues.api_key as string | undefined),
    model_configurations: filteredModelConfigurations,
  };

  // Test the configuration
  if (!isEqual(finalValues, initialValues)) {
    setIsTesting(true);

    const response = await fetch("/api/admin/llm/test", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        provider: providerName,
        ...finalValues,
      }),
    });
    setIsTesting(false);

    if (!response.ok) {
      const errorMsg = (await response.json()).detail;
      setTestError(errorMsg);
      setSubmitting(false);
      return;
    }
  }

  const response = await fetch(
    `${LLM_PROVIDERS_ADMIN_URL}${
      existingLlmProvider ? "" : "?is_creation=true"
    }`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        provider: providerName,
        ...finalValues,
      }),
    }
  );

  if (!response.ok) {
    const errorMsg = (await response.json()).detail;
    const fullErrorMsg = existingLlmProvider
      ? `Failed to update provider: ${errorMsg}`
      : `Failed to enable provider: ${errorMsg}`;
    if (setPopup) {
      setPopup({
        type: "error",
        message: fullErrorMsg,
      });
    } else {
      alert(fullErrorMsg);
    }
    return;
  }

  if (shouldMarkAsDefault) {
    const newLlmProvider = (await response.json()) as LLMProviderView;
    const setDefaultResponse = await fetch(
      `${LLM_PROVIDERS_ADMIN_URL}/${newLlmProvider.id}/default`,
      {
        method: "POST",
      }
    );
    if (!setDefaultResponse.ok) {
      const errorMsg = (await setDefaultResponse.json()).detail;
      const fullErrorMsg = `Failed to set provider as default: ${errorMsg}`;
      if (setPopup) {
        setPopup({
          type: "error",
          message: fullErrorMsg,
        });
      } else {
        alert(fullErrorMsg);
      }
      return;
    }
  }

  mutate(LLM_PROVIDERS_ADMIN_URL);
  onClose();

  const successMsg = existingLlmProvider
    ? "Provider updated successfully!"
    : "Provider enabled successfully!";
  if (!hideSuccess && setPopup) {
    setPopup({
      type: "success",
      message: successMsg,
    });
  } else if (!hideSuccess) {
    alert(successMsg);
  }

  setSubmitting(false);
};
