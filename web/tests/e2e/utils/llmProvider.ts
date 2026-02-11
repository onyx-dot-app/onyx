import type { Page, APIRequestContext } from "@playwright/test";

/**
 * Shared LLM provider provisioning utilities for E2E tests.
 *
 * Many tests require a public LLM provider to be configured (e.g. file uploads
 * need a tokenizer, assistant creation needs a model selector, etc.).
 *
 * Two usage patterns are provided:
 *
 * 1. **Global setup** – `ensureLlmProviderExists` uses a lightweight Playwright
 *    `request` context (no browser) so it can run in `global-setup.ts` before
 *    any browser is launched.
 *
 * 2. **Per-page** – `ensureLlmProviderForPage` accepts a Playwright `Page` and
 *    works through `page.request`, handy in `beforeAll` blocks or fixtures.
 */

const LLM_PROVIDER_PAYLOAD = {
  name: "PW Default Provider",
  provider: "openai",
  api_key: "test-key",
  default_model_name: "gpt-4o",
  is_public: true,
  groups: [],
  personas: [],
};

// ── Helpers for the lightweight `request` context (global-setup) ────────────

/**
 * Ensure at least one public LLM provider exists.
 *
 * Uses the Playwright lightweight `APIRequestContext` — ideal for
 * `global-setup.ts` where no browser is running.
 *
 * @param ctx  An authenticated APIRequestContext (must carry admin cookies).
 * @returns    The provider ID if one was created, or `null` if a public
 *             provider already existed.
 */
export async function ensureLlmProviderExists(
  ctx: APIRequestContext
): Promise<number | null> {
  const listRes = await ctx.get("/api/llm/provider");
  if (!listRes.ok()) {
    throw new Error(
      `[llmProvider] Failed to list LLM providers: ${listRes.status()}`
    );
  }

  const providers: Array<{ id: number; is_public?: boolean }> =
    await listRes.json();
  const hasPublic = providers.some((p) => p.is_public);

  if (hasPublic) {
    return null; // nothing to do
  }

  const createRes = await ctx.put("/api/admin/llm/provider?is_creation=true", {
    data: LLM_PROVIDER_PAYLOAD,
  });
  if (!createRes.ok()) {
    const body = await createRes.text();
    throw new Error(
      `[llmProvider] Failed to create public LLM provider: ${createRes.status()} ${body}`
    );
  }

  const { id } = (await createRes.json()) as { id: number };

  // Set the provider as the default so that get_default_llm() works
  // (e.g. for file upload tokenization).
  const defaultRes = await ctx.post(`/api/admin/llm/provider/${id}/default`);
  if (!defaultRes.ok()) {
    const body = await defaultRes.text();
    console.warn(
      `[llmProvider] Failed to set provider ${id} as default: ${defaultRes.status()} ${body}`
    );
  }

  console.log(`[global-setup] Created public LLM provider (ID: ${id})`);
  return id;
}

// ── Helpers that operate on a Playwright Page (fixtures / beforeAll) ────────

/**
 * Ensure at least one public LLM provider exists, using a Playwright `Page`.
 *
 * Useful inside `test.beforeAll` or custom fixtures.
 *
 * @returns The provider ID if one was created, or `null` if a public
 *          provider already existed.
 */
export async function ensureLlmProviderForPage(
  page: Page
): Promise<number | null> {
  const baseUrl = process.env.BASE_URL || "http://localhost:3000";
  const listRes = await page.request.get(`${baseUrl}/api/llm/provider`);
  if (!listRes.ok()) {
    throw new Error(
      `[llmProvider] Failed to list LLM providers: ${listRes.status()}`
    );
  }

  const providers: Array<{ id: number; is_public?: boolean }> =
    await listRes.json();
  const hasPublic = providers.some((p) => p.is_public);

  if (hasPublic) {
    return null;
  }

  const createRes = await page.request.put(
    `${baseUrl}/api/admin/llm/provider?is_creation=true`,
    { data: LLM_PROVIDER_PAYLOAD }
  );
  if (!createRes.ok()) {
    const body = await createRes.text();
    throw new Error(
      `[llmProvider] Failed to create public LLM provider: ${createRes.status()} ${body}`
    );
  }

  const { id } = (await createRes.json()) as { id: number };

  // Set the provider as the default so that get_default_llm() works
  const defaultRes = await page.request.post(
    `${baseUrl}/api/admin/llm/provider/${id}/default`
  );
  if (!defaultRes.ok()) {
    const body = await defaultRes.text();
    console.warn(
      `[llmProvider] Failed to set provider ${id} as default: ${defaultRes.status()} ${body}`
    );
  }

  console.log(`[llmProvider] Created public LLM provider (ID: ${id})`);
  return id;
}

/**
 * Delete an LLM provider by ID. Logs a warning on failure rather than
 * throwing, since this is typically used in cleanup paths.
 */
export async function deleteLlmProvider(
  page: Page,
  providerId: number
): Promise<void> {
  const baseUrl = process.env.BASE_URL || "http://localhost:3000";
  const res = await page.request.delete(
    `${baseUrl}/api/admin/llm/provider/${providerId}`
  );
  if (!res.ok()) {
    const body = await res.text();
    console.warn(
      `[llmProvider] Failed to delete provider ${providerId}: ${res.status()} ${body}`
    );
  }
}
