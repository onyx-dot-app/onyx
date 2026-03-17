import {
  LLMProviderName,
  LLMProviderView,
  ModelConfiguration,
} from "@/interfaces/llm";
import {
  LLM_ADMIN_URL,
  LLM_PROVIDERS_ADMIN_URL,
} from "@/lib/llmConfig/constants";
import { refreshLlmProviderCaches } from "@/lib/llmConfig/cache";
import { toast } from "@/hooks/useToast";
import isEqual from "lodash/isEqual";
import { parseAzureTargetUri } from "@/lib/azureTargetUri";
import {
  track,
  AnalyticsEvent,
  LLMProviderConfiguredSource,
} from "@/lib/analytics";
import {
  BaseLLMFormValues,
  SubmitLLMProviderParams,
  SubmitOnboardingProviderParams,
  TestApiKeyResult,
  filterModelConfigurations,
  getAutoModeModelConfigurations,
} from "@/sections/modals/llmConfig/utils";

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

  const knownProviders = new Set<string>(Object.values(LLMProviderName));
  track(AnalyticsEvent.CONFIGURED_LLM_PROVIDER, {
    provider: knownProviders.has(providerName) ? providerName : "custom",
    is_creation: !existingLlmProvider,
    source: LLMProviderConfiguredSource.ADMIN_PAGE,
  });

  setSubmitting(false);
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

export const submitOnboardingProvider = async ({
  providerName,
  payload,
  onboardingState,
  onboardingActions,
  isCustomProvider,
  onClose,
  setIsSubmitting,
}: SubmitOnboardingProviderParams): Promise<void> => {
  setIsSubmitting(true);

  // Test credentials
  let result: TestApiKeyResult;
  if (isCustomProvider) {
    result = await testCustomProvider(payload);
  } else {
    result = await testApiKeyHelper(providerName, payload);
  }

  if (!result.ok) {
    toast.error(result.errorMessage);
    setIsSubmitting(false);
    return;
  }

  // Create provider
  const response = await fetch(`${LLM_PROVIDERS_ADMIN_URL}?is_creation=true`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const errorMsg = (await response.json()).detail;
    toast.error(errorMsg);
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
            setIsSubmitting(false);
            return;
          }
        }
      }
    } catch (_e) {
      toast.error("Failed to set new provider as default");
    }
  }

  track(AnalyticsEvent.CONFIGURED_LLM_PROVIDER, {
    provider: isCustomProvider ? "custom" : providerName,
    is_creation: true,
    source: LLMProviderConfiguredSource.CHAT_ONBOARDING,
  });

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
