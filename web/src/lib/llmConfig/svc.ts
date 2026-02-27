/**
 * LLM action functions for mutations.
 *
 * These are async functions for one-off actions that don't need SWR caching.
 *
 * Endpoints:
 * - /api/admin/llm/test/default - Test the default LLM provider connection
 * - /api/admin/llm/default - Set the default LLM model
 * - /api/admin/llm/provider/{id} - Delete an LLM provider
 */

import {
  LLM_ADMIN_URL,
  LLM_PROVIDERS_ADMIN_URL,
} from "@/lib/llmConfig/constants";

/**
 * Test the default LLM provider.
 * Returns true if the default provider is configured and working, false otherwise.
 */
export async function testDefaultProvider(): Promise<boolean> {
  try {
    const response = await fetch(`${LLM_ADMIN_URL}/test/default`, {
      method: "POST",
    });
    return response?.ok || false;
  } catch {
    return false;
  }
}

/**
 * Set the default LLM model.
 * @param providerId - The provider ID
 * @param modelName - The model name within that provider
 * @throws Error with the detail message from the API on failure
 */
export async function setDefaultLlmModel(
  providerId: number,
  modelName: string
): Promise<void> {
  const response = await fetch(`${LLM_ADMIN_URL}/default`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      provider_id: providerId,
      model_name: modelName,
    }),
  });

  if (!response.ok) {
    const errorMsg = (await response.json()).detail;
    throw new Error(errorMsg);
  }
}

/**
 * Delete an LLM provider.
 * @param providerId - The provider ID to delete
 * @throws Error with the detail message from the API on failure
 */
export async function deleteLlmProvider(providerId: number): Promise<void> {
  const response = await fetch(`${LLM_PROVIDERS_ADMIN_URL}/${providerId}`, {
    method: "DELETE",
  });

  if (!response.ok) {
    const errorMsg = (await response.json()).detail;
    throw new Error(errorMsg);
  }
}
