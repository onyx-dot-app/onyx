import { LLMProviderName, LLMProviderView } from "@/interfaces/llm";
import {
  LLM_ADMIN_URL,
  LLM_PROVIDERS_ADMIN_URL,
} from "@/lib/llmConfig/constants";
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

// ─── Submit provider ──────────────────────────────────────────────────────

export interface SubmitProviderParams<
  T extends BaseLLMFormValues = BaseLLMFormValues,
> {
  providerName: string;
  values: T;
  initialValues: T;
  existingLlmProvider?: LLMProviderView;
  shouldMarkAsDefault?: boolean;
  isCustomProvider?: boolean;
  setStatus: (status: Record<string, unknown>) => void;
  setSubmitting: (submitting: boolean) => void;
  onClose: () => void;
  /** Called after successful create/update + set-default. Use for cache refresh, state updates, toasts, etc. */
  onSuccess?: () => void | Promise<void>;
  /** Analytics source for tracking. @default LLMProviderConfiguredSource.ADMIN_PAGE */
  analyticsSource?: LLMProviderConfiguredSource;
}

export async function submitProvider<T extends BaseLLMFormValues>({
  providerName,
  values,
  initialValues,
  existingLlmProvider,
  shouldMarkAsDefault,
  isCustomProvider,
  setStatus,
  setSubmitting,
  onClose,
  onSuccess,
  analyticsSource = LLMProviderConfiguredSource.ADMIN_PAGE,
}: SubmitProviderParams<T>): Promise<void> {
  setSubmitting(true);

  const { test_model_name, api_key, name: rawName, ...rest } = values;
  const testModelName =
    test_model_name ||
    values.model_configurations.find((m) => m.is_visible)?.name ||
    "";

  // ── Test credentials ────────────────────────────────────────────────
  const customConfigChanged = !isEqual(
    values.custom_config,
    initialValues.custom_config
  );

  const normalizedApiBase =
    typeof rest.api_base === "string" && rest.api_base.trim() === ""
      ? undefined
      : rest.api_base;

  // Insert semantics:  undefined/null/""  → null  ("no name")
  // Update semantics:  undefined          → omit  ("don't change")
  //                    null/""            → null   ("clear")
  //                    string             → string ("set")
  const nameForRequest: string | null | undefined = existingLlmProvider
    ? rawName !== undefined
      ? rawName || null
      : undefined
    : rawName || null;

  // For updates: omit api_key when unchanged — signals "not changing credentials"
  // to both the test-skip logic below and the backend's api_key_changed flag.
  const apiKeyUnchanged =
    !!existingLlmProvider &&
    api_key === (initialValues.api_key as string | undefined);
  const apiKeyForRequest = apiKeyUnchanged ? undefined : api_key;

  const finalValues = {
    ...rest,
    ...(nameForRequest !== undefined ? { name: nameForRequest } : {}),
    api_base: normalizedApiBase,
    ...(apiKeyForRequest !== undefined ? { api_key: apiKeyForRequest } : {}),
    api_key_changed: apiKeyForRequest !== undefined,
    custom_config_changed: customConfigChanged,
  };

  // Skip test on updates where api_key is absent (credentials not changing)
  if (
    (!existingLlmProvider || apiKeyForRequest !== undefined) &&
    !isEqual(finalValues, initialValues)
  ) {
    setStatus({ isTesting: true });

    const testResult = await submitLlmTestRequest(
      {
        provider: providerName,
        ...finalValues,
        model: testModelName,
        id: existingLlmProvider?.id,
      },
      "An error occurred while testing the provider."
    );
    setStatus({ isTesting: false });

    if (!testResult.ok) {
      toast.error(testResult.errorMessage);
      setSubmitting(false);
      return;
    }
  }

  // ── Create/update provider ──────────────────────────────────────────
  const response = await fetch(
    `${LLM_PROVIDERS_ADMIN_URL}${
      existingLlmProvider ? "" : "?is_creation=true"
    }`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
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
    setSubmitting(false);
    return;
  }

  // ── Set as default ──────────────────────────────────────────────────
  if (shouldMarkAsDefault && testModelName) {
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
  track(AnalyticsEvent.CONFIGURED_LLM_PROVIDER, {
    provider: knownProviders.has(providerName) ? providerName : "custom",
    is_creation: !existingLlmProvider,
    source: analyticsSource,
  });

  if (onSuccess) await onSuccess();

  setSubmitting(false);
  onClose();
}
