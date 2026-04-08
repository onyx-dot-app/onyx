import { LLMProviderName, LLMProviderView } from "@/interfaces/llm";
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
  TestApiKeyResult,
} from "@/sections/modals/llmConfig/utils";
import { ScopedMutator } from "swr";
import { OnboardingActions, OnboardingState } from "@/interfaces/onboarding";

// ─── Test helpers ─────────────────────────────────────────────────────────

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
    model: modelName ?? (formValues?.test_model_name as string) ?? "",
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

// ─── Unified submit ───────────────────────────────────────────────────────

export interface SubmitProviderParams<
  T extends BaseLLMFormValues = BaseLLMFormValues,
> {
  providerName: string;
  values: T;
  initialValues: T;
  existingLlmProvider?: LLMProviderView;
  shouldMarkAsDefault?: boolean;
  isCustomProvider?: boolean;
  hideSuccess?: boolean;
  setStatus: (status: Record<string, unknown>) => void;
  setSubmitting: (submitting: boolean) => void;
  onClose: () => void;

  // Admin-only
  mutate?: ScopedMutator;

  // Onboarding-only
  onboardingState?: OnboardingState;
  onboardingActions?: OnboardingActions;
}

export async function submitProvider<T extends BaseLLMFormValues>({
  providerName,
  values,
  initialValues,
  existingLlmProvider,
  shouldMarkAsDefault,
  isCustomProvider,
  hideSuccess,
  setStatus,
  setSubmitting,
  onClose,
  mutate,
  onboardingState,
  onboardingActions,
}: SubmitProviderParams<T>): Promise<void> {
  const isOnboarding = !!onboardingState && !!onboardingActions;
  setSubmitting(true);

  const { test_model_name, api_key, ...rest } = values;
  const testModelName =
    test_model_name ||
    values.model_configurations.find((m) => m.is_visible)?.name ||
    "";

  // ── Test credentials ────────────────────────────────────────────────
  if (isOnboarding) {
    // Onboarding always tests
    const result = isCustomProvider
      ? await testCustomProvider(values as unknown as Record<string, unknown>)
      : await testApiKeyHelper(
          providerName,
          values as unknown as Record<string, unknown>
        );

    if (!result.ok) {
      toast.error(result.errorMessage);
      setSubmitting(false);
      return;
    }
  } else {
    // Admin: only test if values changed
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
      api_key,
      api_key_changed:
        api_key !== (initialValues.api_key as string | undefined),
      custom_config_changed: customConfigChanged,
    };

    if (!isEqual(finalValues, initialValues)) {
      setStatus({ isTesting: true });

      const testResponse = await fetch("/api/admin/llm/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: providerName,
          ...finalValues,
          model: testModelName,
          id: existingLlmProvider?.id,
        }),
      });
      setStatus({ isTesting: false });

      if (!testResponse.ok) {
        const errorMsg = (await testResponse.json()).detail;
        toast.error(errorMsg);
        setSubmitting(false);
        return;
      }
    }
  }

  // ── Create/update provider ──────────────────────────────────────────
  const payloadForPut = isOnboarding
    ? values
    : (() => {
        const customConfigChanged = !isEqual(
          values.custom_config,
          initialValues.custom_config
        );
        const normalizedApiBase =
          typeof rest.api_base === "string" && rest.api_base.trim() === ""
            ? undefined
            : rest.api_base;
        return {
          ...rest,
          api_base: normalizedApiBase,
          api_key,
          api_key_changed:
            api_key !== (initialValues.api_key as string | undefined),
          custom_config_changed: customConfigChanged,
          id: existingLlmProvider?.id,
        };
      })();

  const response = await fetch(
    `${LLM_PROVIDERS_ADMIN_URL}${
      existingLlmProvider ? "" : "?is_creation=true"
    }`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider: providerName,
        ...payloadForPut,
      }),
    }
  );

  if (!response.ok) {
    const errorMsg = (await response.json()).detail;
    const fullErrorMsg = existingLlmProvider
      ? `Failed to update provider: ${errorMsg}`
      : `Failed to enable provider: ${errorMsg}`;
    toast.error(fullErrorMsg);
    setSubmitting(false);
    return;
  }

  // ── Set as default ──────────────────────────────────────────────────
  const shouldSetDefault = isOnboarding
    ? (onboardingState.data?.llmProviders ?? []).length === 0
    : shouldMarkAsDefault;

  if (shouldSetDefault && testModelName) {
    try {
      const newLlmProvider = await response.json();
      if (newLlmProvider?.id != null) {
        const setDefaultResponse = await fetch(`${LLM_ADMIN_URL}/default`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            provider_id: newLlmProvider.id,
            model_name: testModelName,
          }),
        });
        if (!setDefaultResponse.ok) {
          const err = await setDefaultResponse.json().catch(() => ({}));
          toast.error(err?.detail ?? "Failed to set provider as default");
          setSubmitting(false);
          return;
        }
      }
    } catch {
      toast.error("Failed to set new provider as default");
    }
  }

  // ── Post-success ────────────────────────────────────────────────────
  const knownProviders = new Set<string>(Object.values(LLMProviderName));

  if (isOnboarding) {
    onboardingActions.updateData({
      llmProviders: [
        ...(onboardingState.data?.llmProviders ?? []),
        isCustomProvider ? "custom" : providerName,
      ],
    });
    onboardingActions.setButtonActive(true);
  } else {
    if (mutate) await refreshLlmProviderCaches(mutate);

    if (!hideSuccess) {
      const successMsg = existingLlmProvider
        ? "Provider updated successfully!"
        : "Provider enabled successfully!";
      toast.success(successMsg);
    }
  }

  track(AnalyticsEvent.CONFIGURED_LLM_PROVIDER, {
    provider: knownProviders.has(providerName) ? providerName : "custom",
    is_creation: !existingLlmProvider,
    source: isOnboarding
      ? LLMProviderConfiguredSource.CHAT_ONBOARDING
      : LLMProviderConfiguredSource.ADMIN_PAGE,
  });

  setSubmitting(false);
  onClose();
}
