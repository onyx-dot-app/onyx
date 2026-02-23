/**
 * LLM action functions for mutations.
 *
 * These are async functions for one-off actions that don't need SWR caching.
 *
 * Endpoints:
 * - /api/admin/llm/test/default - Test the default LLM provider connection
 * - /api/admin/llm/provider/{id}/default - Set a provider as the default
 */

import { LLM_PROVIDERS_ADMIN_URL } from "@/app/admin/configuration/llm/constants";

/**
 * Test the default LLM provider.
 * Returns true if the default provider is configured and working, false otherwise.
 */
export async function testDefaultProvider(): Promise<boolean> {
  try {
    const response = await fetch("/api/admin/llm/test/default", {
      method: "POST",
    });
    return response?.ok || false;
  } catch {
    return false;
  }
}

/**
 * Set a provider as the default LLM provider.
 * @param compositeValue - A string in the format "{providerId}:{modelName}"
 * @throws Error with the detail message from the API on failure
 */
export async function setDefaultLLMProvider(
  compositeValue: string
): Promise<void> {
  const separatorIndex = compositeValue.indexOf(":");
  const providerId = compositeValue.slice(0, separatorIndex);

  const response = await fetch(
    `${LLM_PROVIDERS_ADMIN_URL}/${providerId}/default`,
    { method: "POST" }
  );

  if (!response.ok) {
    const errorMsg = (await response.json()).detail;
    throw new Error(errorMsg);
  }
}
