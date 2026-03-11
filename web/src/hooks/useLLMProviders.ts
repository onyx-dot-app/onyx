"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import {
  LLMProviderDescriptor,
  LLMProviderResponse,
  LLMProviderView,
  WellKnownLLMProviderDescriptor,
} from "@/interfaces/llm";
import { LLM_PROVIDERS_ADMIN_URL } from "@/lib/llmConfig/constants";

/**
 * Fetches configured LLM providers accessible to the current user.
 *
 * Hits the **non-admin** endpoints which return `LLMProviderDescriptor`
 * (no `id` or sensitive fields like `api_key`). Use this hook in
 * user-facing UI (chat, popovers, onboarding) where you need the list
 * of providers and their visible models but don't need admin-level details.
 *
 * The backend wraps the provider list in an `LLMProviderResponse` envelope
 * that also carries the global default text and vision models. This hook
 * unwraps `.providers` for convenience while still exposing the defaults.
 *
 * **Endpoints:**
 * - No `personaId` → `GET /api/llm/provider`
 *   Returns all public providers plus restricted providers the user can
 *   access via group membership.
 * - With `personaId` → `GET /api/llm/persona/{personaId}/providers`
 *   Returns providers scoped to a specific persona, respecting RBAC
 *   restrictions. Use this when displaying model options for a particular
 *   assistant.
 *
 * @param personaId - Optional persona ID for RBAC-scoped providers.
 *
 * @returns
 * - `llmProviders` — The array of provider descriptors, or `undefined`
 *    while loading.
 * - `defaultText` — The global (or persona-overridden) default text model.
 * - `defaultVision` — The global (or persona-overridden) default vision model.
 * - `isLoading` — `true` until the first successful response or error.
 * - `error` — The SWR error object, if any.
 * - `refetch` — SWR `mutate` function to trigger a revalidation.
 */
export function useLLMProviders(personaId?: number) {
  const url =
    personaId !== undefined
      ? `/api/llm/persona/${personaId}/providers`
      : "/api/llm/provider";

  const { data, error, mutate } = useSWR<
    LLMProviderResponse<LLMProviderDescriptor>
  >(url, errorHandlingFetcher, {
    revalidateOnFocus: false,
    dedupingInterval: 60000,
  });

  return {
    llmProviders: data?.providers,
    defaultText: data?.default_text ?? null,
    defaultVision: data?.default_vision ?? null,
    isLoading: !error && !data,
    error,
    refetch: mutate,
  };
}

/**
 * Fetches configured LLM providers via the **admin** endpoint.
 *
 * Hits `GET /api/admin/llm/provider` which returns `LLMProviderView` —
 * the full provider object including `id`, `api_key` (masked),
 * group/persona assignments, and all other admin-visible fields.
 *
 * Use this hook on admin pages (e.g. the LLM Configuration page) where
 * you need provider IDs for mutations (setting defaults, editing, deleting)
 * or need to display admin-only metadata. **Do not use in user-facing UI**
 * — use `useLLMProviders` instead.
 *
 * @returns
 * - `llmProviders` — The array of full provider views, or `undefined`
 *    while loading.
 * - `defaultText` — The global default text model.
 * - `defaultVision` — The global default vision model.
 * - `isLoading` — `true` until the first successful response or error.
 * - `error` — The SWR error object, if any.
 * - `refetch` — SWR `mutate` function to trigger a revalidation.
 */
export function useAdminLLMProviders() {
  const { data, error, mutate } = useSWR<LLMProviderResponse<LLMProviderView>>(
    LLM_PROVIDERS_ADMIN_URL,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 60000,
    }
  );

  return {
    llmProviders: data?.providers,
    defaultText: data?.default_text ?? null,
    defaultVision: data?.default_vision ?? null,
    isLoading: !error && !data,
    error,
    refetch: mutate,
  };
}

/**
 * Fetches the catalog of well-known (built-in) LLM providers.
 *
 * Hits `GET /api/admin/llm/built-in/options` which returns the static
 * list of provider descriptors that Onyx ships with out of the box
 * (OpenAI, Anthropic, Vertex AI, Bedrock, Azure, Ollama, OpenRouter,
 * etc.). Each descriptor includes the provider's known models and the
 * recommended default model.
 *
 * Used primarily on the LLM Configuration page and onboarding flows
 * to show which providers are available to set up, and to pre-populate
 * model lists before the user has entered credentials.
 *
 * @returns
 * - `wellKnownLLMProviders` — The array of built-in provider descriptors,
 *    or `null` while loading.
 * - `isLoading` — `true` until the first successful response or error.
 * - `error` — The SWR error object, if any.
 * - `mutate` — SWR `mutate` function to trigger a revalidation.
 */
export function useWellKnownLLMProviders() {
  const {
    data: wellKnownLLMProviders,
    error,
    isLoading,
    mutate,
  } = useSWR<WellKnownLLMProviderDescriptor[]>(
    "/api/admin/llm/built-in/options",
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 60000,
    }
  );

  return {
    wellKnownLLMProviders: wellKnownLLMProviders ?? null,
    isLoading,
    error,
    mutate,
  };
}
