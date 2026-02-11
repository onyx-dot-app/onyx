import type { Page, APIRequestContext } from "@playwright/test";
import { OnyxApiClient } from "./onyxApiClient";

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
 * 2. **Per-page** – `ensureLlmProviderForPage` / `deleteLlmProvider` delegate
 *    to `OnyxApiClient` for use in `beforeAll` blocks or fixtures.
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

// ── Lightweight `APIRequestContext` variant (for global-setup.ts) ────────────

/**
 * Ensure at least one public LLM provider exists and is set as default.
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
  // Use the admin endpoint which returns LLMProviderView (includes is_public)
  const listRes = await ctx.get("/api/admin/llm/provider");
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

// ── Page-based helpers (delegate to OnyxApiClient) ──────────────────────────

/**
 * Ensure at least one public LLM provider exists, using a Playwright `Page`.
 *
 * Delegates to `OnyxApiClient.ensurePublicProvider()`. The page must be
 * authenticated as an admin.
 *
 * @returns The provider ID if one was created, or `null` if a public
 *          provider already existed.
 */
export async function ensureLlmProviderForPage(
  page: Page
): Promise<number | null> {
  const client = new OnyxApiClient(page);
  return client.ensurePublicProvider();
}

/**
 * Delete an LLM provider by ID.
 *
 * Delegates to `OnyxApiClient.deleteProvider()`. The page must be
 * authenticated as an admin.
 */
export async function deleteLlmProvider(
  page: Page,
  providerId: number
): Promise<void> {
  const client = new OnyxApiClient(page);
  await client.deleteProvider(providerId);
}
