import {
  LLMProviderView,
  ModelConfiguration,
  WellKnownLLMProviderDescriptor,
} from "@/interfaces/llm";
import {
  LLM_ADMIN_URL,
  LLM_PROVIDERS_ADMIN_URL,
} from "@/lib/llmConfig/constants";
import { refreshLlmProviderCaches } from "@/lib/llmConfig/cache";
import { toast } from "@/hooks/useToast";
import * as Yup from "yup";
import isEqual from "lodash/isEqual";
import { ScopedMutator } from "swr";
import { OnboardingActions, OnboardingState } from "@/interfaces/onboarding";
import { parseAzureTargetUri } from "@/lib/azureTargetUri";

export const buildDefaultInitialValues = (
  existingLlmProvider?: LLMProviderView,
  modelConfigurations?: ModelConfiguration[]
) => {
  const defaultModelName =
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

export const submitLLMProvider = async <T extends BaseLLMFormValues>({
  providerName,
  values,
  initialValues,
  modelConfigurations,
  existingLlmProvider,
  shouldMarkAsDefault,
  hideSuccess,
  setIsTesting,
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

  const customConfigChanged = !isEqual(
    values.custom_config,
    initialValues.custom_config
  );

  const normalizedApiBase =
    typeof rest.api_base === "string" && rest.api_base.trim() === ""
      ? undefined
      : rest.api_base;

  const finalValues = {
    ...rest,
    api_base: normalizedApiBase,
    default_model_name: finalDefaultModelName,
    api_key,
    api_key_changed: api_key !== (initialValues.api_key as string | undefined),
    custom_config_changed: customConfigChanged,
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
        model: finalDefaultModelName,
        id: existingLlmProvider?.id,
      }),
    });
    setIsTesting(false);

    if (!response.ok) {
      const errorMsg = (await response.json()).detail;
      toast.error(errorMsg);
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
        id: existingLlmProvider?.id,
      }),
    }
  );

  if (!response.ok) {
    const errorMsg = (await response.json()).detail;
    const fullErrorMsg = existingLlmProvider
      ? `Failed to update provider: ${errorMsg}`
      : `Failed to enable provider: ${errorMsg}`;
    toast.error(fullErrorMsg);
    return;
  }

  if (shouldMarkAsDefault) {
    const newLlmProvider = (await response.json()) as LLMProviderView;
    const setDefaultResponse = await fetch(`${LLM_ADMIN_URL}/default`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        provider_id: newLlmProvider.id,
        model_name: finalDefaultModelName,
      }),
    });
    if (!setDefaultResponse.ok) {
      const errorMsg = (await setDefaultResponse.json()).detail;
      toast.error(`Failed to set provider as default: ${errorMsg}`);
      return;
    }
  }

  await refreshLlmProviderCaches(mutate);
  onClose();

  if (!hideSuccess) {
    const successMsg = existingLlmProvider
      ? "Provider updated successfully!"
      : "Provider enabled successfully!";
    toast.success(successMsg);
  }

  setSubmitting(false);
};

// ── Onboarding helpers (migrated from llmConnectionHelpers.ts) ──────────

export type TestApiKeyResult =
  | { ok: true }
  | { ok: false; errorMessage: string };

const submitLlmTestRequest = async (
  payload: Record<string, unknown>,
  fallbackErrorMessage: string
): Promise<TestApiKeyResult> => {
  try {
    const response = await fetch("/api/admin/llm/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const errorMsg = (await response.json()).detail;
      return { ok: false, errorMessage: errorMsg };
    }

    return { ok: true };
  } catch {
    return {
      ok: false,
      errorMessage: fallbackErrorMessage,
    };
  }
};

export const testApiKeyHelper = async (
  providerName: string,
  formValues: Record<string, unknown>,
  apiKey?: string,
  modelName?: string,
  customConfigOverride?: Record<string, unknown>
): Promise<TestApiKeyResult> => {
  let finalApiBase = formValues?.api_base;
  let finalApiVersion = formValues?.api_version;
  let finalDeploymentName = formValues?.deployment_name;

  if (providerName === "azure" && formValues?.target_uri) {
    try {
      const { url, apiVersion, deploymentName } = parseAzureTargetUri(
        formValues.target_uri as string
      );
      finalApiBase = url.origin;
      finalApiVersion = apiVersion;
      finalDeploymentName = deploymentName || "";
    } catch {
      // leave defaults so validation can surface errors upstream
    }
  }

  const payload = {
    api_key: apiKey ?? formValues?.api_key,
    api_base: finalApiBase,
    api_version: finalApiVersion,
    deployment_name: finalDeploymentName,
    provider: providerName,
    api_key_changed: true,
    custom_config_changed: true,
    custom_config: {
      ...((formValues?.custom_config as Record<string, unknown>) ?? {}),
      ...(customConfigOverride ?? {}),
    },
    model: modelName ?? (formValues?.default_model_name as string) ?? "",
  };

  return await submitLlmTestRequest(
    payload,
    "An error occurred while testing the API key."
  );
};

export const testCustomProvider = async (
  formValues: Record<string, unknown>
): Promise<TestApiKeyResult> => {
  return await submitLlmTestRequest(
    { ...formValues },
    "An error occurred while testing the custom provider."
  );
};

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
  setApiStatus: (status: string) => void;
  setShowApiMessage: (show: boolean) => void;
}

/**
 * Onboarding submission flow:
 * 1. Test credentials
 * 2. Create provider
 * 3. Set as default if first provider
 * 4. Update onboarding state
 */
export const submitOnboardingProvider = async ({
  providerName,
  payload,
  onboardingState,
  onboardingActions,
  isCustomProvider,
  onClose,
  setIsSubmitting,
  setApiStatus,
  setShowApiMessage,
}: SubmitOnboardingProviderParams): Promise<void> => {
  setIsSubmitting(true);
  setApiStatus("loading");
  setShowApiMessage(true);

  // Test credentials
  let result: TestApiKeyResult;
  if (isCustomProvider) {
    result = await testCustomProvider(payload);
  } else {
    result = await testApiKeyHelper(providerName, payload);
  }

  if (!result.ok) {
    toast.error(result.errorMessage);
    setApiStatus("error");
    setIsSubmitting(false);
    return;
  }
  setApiStatus("success");

  // Create provider
  const response = await fetch(`${LLM_PROVIDERS_ADMIN_URL}?is_creation=true`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const errorMsg = (await response.json()).detail;
    console.error("Failed to create LLM provider", errorMsg);
    toast.error(errorMsg);
    setApiStatus("error");
    setIsSubmitting(false);
    return;
  }

  // Set as default if first provider
  if (
    onboardingState?.data?.llmProviders == null ||
    onboardingState.data.llmProviders.length === 0
  ) {
    try {
      const newLlmProvider = await response.json();
      if (newLlmProvider?.id != null) {
        const defaultModelName =
          (payload as Record<string, string>).default_model_name ??
          (payload as Record<string, ModelConfiguration[]>)
            .model_configurations?.[0]?.name ??
          "";

        if (defaultModelName) {
          const setDefaultResponse = await fetch(`${LLM_ADMIN_URL}/default`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              provider_id: newLlmProvider.id,
              model_name: defaultModelName,
            }),
          });
          if (!setDefaultResponse.ok) {
            const err = await setDefaultResponse.json().catch(() => ({}));
            toast.error(err?.detail ?? "Failed to set provider as default");
            setApiStatus("error");
            setIsSubmitting(false);
            return;
          }
        }
      }
    } catch (_e) {
      console.error("Failed to set new provider as default", _e);
    }
  }

  // Update onboarding state
  onboardingActions.updateData({
    llmProviders: [
      ...(onboardingState?.data.llmProviders ?? []),
      isCustomProvider ? "custom" : providerName,
    ],
  });
  onboardingActions.setButtonActive(true);

  setIsSubmitting(false);
  onClose();
};
