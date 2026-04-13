"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  LLMProviderDescriptor,
  LLMProviderName,
  LLMProviderResponse,
  LLMProviderView,
  WellKnownLLMProviderDescriptor,
} from "@/interfaces/llm";

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
      ? SWR_KEYS.llmProvidersForPersona(personaId)
      : SWR_KEYS.llmProviders;

  // `revalidateIfStale` is intentionally left at its default (true), unlike
  // `useAdminLLMProviders` below. Admin edits call `refreshLlmProviderCaches`,
  // but persona-scoped keys are orphaned when that runs, so `mutate` on them
  // is a no-op. Mount-time revalidation picks up the edits on next nav.
  // `dedupingInterval: 60000` keeps this off the hot path.
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
    SWR_KEYS.adminLlmProviders,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateIfStale: false,
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
/**
 * Fetches the descriptor for a single well-known (built-in) LLM provider.
 *
 * Hits `GET /api/admin/llm/built-in/options/{providerEndpoint}` which returns
 * the provider descriptor including its known models and the recommended
 * default model.
 *
 * Used inside individual provider modals to pre-populate model lists
 * before the user has entered credentials.
 *
 * @param providerName - The provider's API endpoint name (e.g. "openai", "anthropic").
 *   Pass `null` to suppress the request.
 */
export function useWellKnownLLMProvider(providerName: LLMProviderName) {
  const { data, error, isLoading } = useSWR<WellKnownLLMProviderDescriptor>(
    providerName && providerName !== LLMProviderName.CUSTOM
      ? SWR_KEYS.wellKnownLlmProvider(providerName)
      : null,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateIfStale: false,
      dedupingInterval: 60000,
    }
  );

  return {
    wellKnownLLMProvider: data ?? null,
    isLoading,
    error,
  };
}

export interface CustomProviderOption {
  value: string;
  label: string;
}

/**
 * Fetches the list of LiteLLM provider names available for custom provider
 * configuration (i.e. providers that don't have a dedicated well-known modal).
 *
 * Hits `GET /api/admin/llm/custom-provider-names`.
 */
export function useCustomProviderNames() {
  const { data, error, isLoading } = useSWR<CustomProviderOption[]>(
    SWR_KEYS.customProviderNames,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateIfStale: false,
      dedupingInterval: 60000,
    }
  );

  return {
    customProviderNames: data ?? null,
    isLoading,
    error,
  };
}

export function useWellKnownLLMProviders() {
  const {
    data: wellKnownLLMProviders,
    error,
    isLoading,
    mutate,
  } = useSWR<WellKnownLLMProviderDescriptor[]>(
    SWR_KEYS.wellKnownLlmProviders,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateIfStale: false,
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
