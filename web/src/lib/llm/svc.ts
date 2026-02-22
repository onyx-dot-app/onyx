/**
 * LLM action functions for mutations.
 *
 * These are async functions for one-off actions that don't need SWR caching.
 *
 * Endpoints:
 * - /api/admin/llm/test/default - Test the default LLM provider connection
 */

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
