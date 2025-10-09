import { Page } from "@playwright/test";

export type LLMProviderParams = {
  name: string;
  provider: string;
  apiKey?: string;
  defaultModelName: string;
  fastDefaultModelName?: string;
  modelConfigurations?: Array<{
    name: string;
    isVisible: boolean;
  }>;
};

/**
 * Creates an LLM provider via the admin API
 */
export async function createLLMProvider(
  page: Page,
  params: LLMProviderParams
): Promise<void> {
  const {
    name,
    provider,
    apiKey = "test-api-key",
    defaultModelName,
    fastDefaultModelName,
    modelConfigurations = [],
  } = params;

  // Build the request payload
  const payload = {
    name,
    provider,
    api_key: apiKey,
    api_key_changed: true,
    default_model_name: defaultModelName,
    fast_default_model_name: fastDefaultModelName,
    is_public: true,
    groups: [],
    model_configurations: modelConfigurations.map((mc) => ({
      name: mc.name,
      is_visible: mc.isVisible,
    })),
  };

  // Call the admin API to create the provider
  const response = await page.request.put(
    "http://localhost:3000/api/admin/llm/provider?is_creation=true",
    {
      data: payload,
      headers: {
        "Content-Type": "application/json",
      },
    }
  );

  if (!response.ok()) {
    const errorText = await response.text();
    throw new Error(
      `Failed to create LLM provider: ${response.status()} - ${errorText}`
    );
  }
}

/**
 * Deletes an LLM provider by name
 */
export async function deleteLLMProvider(
  page: Page,
  providerName: string
): Promise<void> {
  // First, get all providers to find the ID
  const listResponse = await page.request.get(
    "http://localhost:3000/api/admin/llm/provider"
  );

  if (!listResponse.ok()) {
    throw new Error(`Failed to list LLM providers: ${listResponse.status()}`);
  }

  const providers = await listResponse.json();
  const provider = providers.find((p: any) => p.name === providerName);

  if (!provider) {
    throw new Error(`Provider ${providerName} not found`);
  }

  // Delete the provider
  const deleteResponse = await page.request.delete(
    `http://localhost:3000/api/admin/llm/provider/${provider.id}`
  );

  if (!deleteResponse.ok()) {
    throw new Error(
      `Failed to delete LLM provider: ${deleteResponse.status()}`
    );
  }
}
