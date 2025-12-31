import { ModelConfiguration } from "@/app/admin/configuration/llm/interfaces";
import { parseAzureTargetUri } from "@/lib/azureTargetUri";

export const buildInitialValues = () => ({
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
  deployment_name: "",
  target_uri: "",
});

export const getModelOptions = (
  fetchedModelConfigurations: Array<{ name: string }>
) => {
  return fetchedModelConfigurations.map((model) => ({
    label: model.name,
    value: model.name,
  }));
};

export type TestApiKeyResult =
  | { ok: true }
  | { ok: false; errorMessage: string };

const submitLlmTestRequest = async (
  payload: any,
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
  } catch (err) {
    return {
      ok: false,
      errorMessage: fallbackErrorMessage,
    };
  }
};

export const testApiKeyHelper = async (
  providerName: string,
  formValues: any,
  apiKey?: string,
  modelName?: string,
  customConfigOverride?: Record<string, any>
): Promise<TestApiKeyResult> => {
  let finalApiBase = formValues?.api_base;
  let finalApiVersion = formValues?.api_version;
  let finalDeploymentName = formValues?.deployment_name;

  if (providerName === "azure" && formValues?.target_uri) {
    try {
      const { url, apiVersion, deploymentName } = parseAzureTargetUri(
        formValues.target_uri
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
    custom_config: {
      ...(formValues?.custom_config ?? {}),
      ...(customConfigOverride ?? {}),
    },
    default_model_name: modelName ?? formValues?.default_model_name ?? "",
    model_configurations: [
      ...(formValues.model_configurations || []).map(
        (model: ModelConfiguration) => ({
          name: model.name,
          is_visible: true,
        })
      ),
    ],
  };

  return await submitLlmTestRequest(
    payload,
    "An error occurred while testing the API key."
  );
};

export const testCustomProvider = async (
  formValues: any
): Promise<TestApiKeyResult> => {
  const payload = {
    ...formValues,
  };
  return await submitLlmTestRequest(
    payload,
    "An error occurred while testing the custom provider."
  );
};
