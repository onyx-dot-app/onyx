import {
  ModelConfiguration,
  WellKnownLLMProviderDescriptor,
} from "@/app/admin/configuration/llm/interfaces";
import { dynamicProviderConfigs } from "@/app/admin/configuration/llm/utils";

export const buildInitialValues = (
  llmDescriptor?: WellKnownLLMProviderDescriptor
) => ({
  api_base: llmDescriptor?.default_api_base ?? "",
  default_model_name: llmDescriptor?.default_model ?? "",
  api_key: "",
  api_key_changed: true,
  api_version: "",
  custom_config: {},
  deployment_name: "",
  target_uri: "",
  fast_default_model_name:
    llmDescriptor?.default_fast_model ?? llmDescriptor?.default_model ?? "",
  name: llmDescriptor?.name ?? "Default",
  provider: llmDescriptor?.name ?? "",
  model_configurations:
    llmDescriptor?.model_configurations.map((model) => ({
      name: model.name,
      is_visible: true,
      max_input_tokens: model.max_input_tokens,
      supports_image_input: model.supports_image_input,
    })) ?? [],
  groups: [],
  is_public: true,
});

export const getModelOptions = (
  llmDescriptor: WellKnownLLMProviderDescriptor | undefined,
  fetchedModelConfigurations: Array<{ name: string }>
) => {
  if (!llmDescriptor) return [] as Array<{ label: string; value: string }>;
  const modelsToUse =
    fetchedModelConfigurations.length > 0
      ? fetchedModelConfigurations
      : llmDescriptor.model_configurations;
  return modelsToUse.map((model) => ({ label: model.name, value: model.name }));
};

export const canProviderFetchModels = (
  llmDescriptor: WellKnownLLMProviderDescriptor | undefined
) => {
  if (!llmDescriptor) return false;
  return !!dynamicProviderConfigs[llmDescriptor.name];
};

export type TestApiKeyResult =
  | { ok: true }
  | { ok: false; errorMessage: string };

export const testApiKeyHelper = async (
  llmDescriptor: WellKnownLLMProviderDescriptor,
  initialValues: any,
  formValues: any,
  apiKey: string
): Promise<TestApiKeyResult> => {
  try {
    let finalApiBase = formValues?.api_base;
    let finalApiVersion = formValues?.api_version;
    let finalDeploymentName = formValues?.deployment_name;

    if (llmDescriptor.name === "azure" && formValues?.target_uri) {
      const url = new URL(formValues.target_uri);
      finalApiBase = url.origin;
      finalApiVersion = url.searchParams.get("api-version") || "";
      const pathMatch = url.pathname.match(/\/openai\/deployments\/([^\/]+)/);
      finalDeploymentName = pathMatch?.[1] || "";
    }

    const payload = {
      api_key: apiKey,
      api_base: finalApiBase,
      api_version: finalApiVersion,
      deployment_name: finalDeploymentName,
      provider: llmDescriptor.name,
      api_key_changed: true,
      default_model_name: initialValues.default_model_name,
      model_configurations: [
        ...formValues.model_configurations.map((model: ModelConfiguration) => ({
          name: model.name,
          is_visible: true,
        })),
      ],
    };

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
      errorMessage: "An error occurred while testing the API key.",
    };
  }
};
