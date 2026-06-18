"use client";

import { useCallback, useMemo } from "react";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useCurrentAgent } from "@/lib/agents/hooks";
import {
  LLMProviderDescriptor,
  LLMProviderName,
  LLMProviderResponse,
  LLMProviderView,
  ModelConfiguration,
  WellKnownLLMProviderDescriptor,
} from "@/lib/languageModels/types";

// ---------------------------------------------------------------------------
// Raw API shapes — local to this module, never exposed to consumers.
// The enrichment step below populates `effectiveDisplayName` before anything
// leaves this file, so consumers always receive the full `ModelConfiguration`.
// ---------------------------------------------------------------------------

type RawModelConfiguration = Omit<ModelConfiguration, "effectiveDisplayName">;

type RawLLMProviderDescriptor = Omit<
  LLMProviderDescriptor,
  "model_configurations"
> & {
  model_configurations: RawModelConfiguration[];
};

type RawLLMProviderView = Omit<LLMProviderView, "model_configurations"> & {
  model_configurations: RawModelConfiguration[];
};

type RawWellKnownLLMProviderDescriptor = Omit<
  WellKnownLLMProviderDescriptor,
  "known_models"
> & { known_models: RawModelConfiguration[] };

// ---------------------------------------------------------------------------
// Enrichment — private helpers
// ---------------------------------------------------------------------------

function enrichModelConfiguration(
  mc: RawModelConfiguration
): ModelConfiguration {
  return {
    ...mc,
    effectiveDisplayName: mc.custom_display_name || mc.display_name || mc.name,
  };
}

function enrichDescriptors(
  providers: RawLLMProviderDescriptor[]
): LLMProviderDescriptor[] {
  return providers.map((p) => ({
    ...p,
    model_configurations: p.model_configurations.map(enrichModelConfiguration),
  }));
}

function enrichViews(providers: RawLLMProviderView[]): LLMProviderView[] {
  return providers.map((p) => ({
    ...p,
    model_configurations: p.model_configurations.map(enrichModelConfiguration),
  }));
}

// ---------------------------------------------------------------------------

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
 * - No `agentId` → `GET /api/llm/provider`
 *   Returns all public providers plus restricted providers the user can
 *   access via group membership.
 * - With `agentId` → `GET /api/llm/persona/{agentId}/providers`
 *   Returns providers scoped to a specific agent, respecting RBAC
 *   restrictions. Use this when displaying model options for a particular
 *   assistant.
 *
 * @param agentId - Optional agent ID for RBAC-scoped providers.
 *
 * @returns
 * - `llmProviders` — The array of provider descriptors, or `undefined`
 *    while loading.
 * - `defaultText` — The global (or agent-overridden) default text model.
 * - `defaultVision` — The global (or agent-overridden) default vision model.
 * - `isLoading` — `true` until the first successful response or error.
 * - `error` — The SWR error object, if any.
 * - `refetch` — SWR `mutate` function to trigger a revalidation.
 */
export function useLLMProviders(agentId?: number) {
  const url =
    agentId !== undefined
      ? SWR_KEYS.llmProvidersForPersona(agentId)
      : SWR_KEYS.llmProviders;

  // `revalidateIfStale` is intentionally left at its default (true), unlike
  // `useAdminLLMProviders` below. Admin edits call `refreshLlmProviderCaches`,
  // but agent-scoped keys are orphaned when that runs, so `mutate` on them
  // is a no-op. Mount-time revalidation picks up the edits on next nav.
  // `dedupingInterval: 60000` keeps this off the hot path.
  const {
    data: raw,
    error,
    mutate,
  } = useSWR<LLMProviderResponse<RawLLMProviderDescriptor>>(
    url,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 60000,
    }
  );

  const data = useMemo(
    () => (raw ? { ...raw, providers: enrichDescriptors(raw.providers) } : raw),
    [raw]
  );

  return {
    llmProviders: data?.providers,
    defaultText: data?.default_text ?? null,
    defaultVision: data?.default_vision ?? null,
    isLoading: !error && !data,
    error,
    refetch: mutate as unknown as () => Promise<
      LLMProviderResponse<LLMProviderDescriptor> | undefined
    >,
  };
}

/**
 * Resolves the active agent via `useCurrentAgent` and fetches that agent's
 * LLM providers via `useLLMProviders`. User-facing model UIs (chat model
 * selectors, popovers) consistently need exactly this pairing, so this hook
 * keeps the resolution in one place instead of repeating it at each call site.
 */
export function useCurrentAgentLLMProviders() {
  const currentAgent = useCurrentAgent();
  return useLLMProviders(currentAgent?.id);
}

/**
 * Fetches configured LLM providers via the **admin** endpoint.
 *
 * Hits `GET /api/admin/llm/provider` which returns `LLMProviderView` —
 * the full provider object including `id`, `api_key` (masked),
 * group/agent assignments, and all other admin-visible fields.
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
  const {
    data: raw,
    error,
    mutate,
  } = useSWR<LLMProviderResponse<RawLLMProviderView>>(
    SWR_KEYS.adminLlmProviders,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateIfStale: false,
      dedupingInterval: 60000,
    }
  );

  const data = useMemo(
    () => (raw ? { ...raw, providers: enrichViews(raw.providers) } : raw),
    [raw]
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
  const {
    data: raw,
    error,
    isLoading,
  } = useSWR<RawWellKnownLLMProviderDescriptor>(
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

  const data = useMemo(
    () =>
      raw
        ? {
            ...raw,
            known_models: raw.known_models.map(enrichModelConfiguration),
          }
        : raw,
    [raw]
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

export interface DefaultLlmReference {
  providerName: string;
  modelName: string;
}

export interface LlmDefaults {
  /** Raw provider list, passed through from `useLLMProviders`. */
  llmProviders: LLMProviderDescriptor[] | undefined;
  /** True iff any provider exposes at least one visible model. */
  hasAnyLlm: boolean;
  /** True iff any provider exposes a visible model with `supports_image_input`. */
  hasAnyVisionLlm: boolean;
  /**
   * The admin-configured default text model, resolved to the form-friendly
   * `{ providerName, modelName }` shape. The backend stores
   * `default_text` as `{ provider_id, model_name }`; this hook joins
   * `provider_id` against the providers list to recover the human-facing
   * provider `name`, which is what `validate_contextual_rag_model` looks
   * up via `fetch_existing_llm_provider(name=...)`.
   */
  defaultLlm: DefaultLlmReference | null;
  /**
   * The admin-configured default *vision* model, resolved to the same
   * `{ providerName, modelName }` shape as `defaultLlm`. Mirrors the
   * resolution path of `defaultLlm` but for `default_vision`. Used by
   * indexing-time captioning and any other vision-only feature.
   */
  defaultVision: DefaultLlmReference | null;
  isLoading: boolean;
}

/**
 * Derived view over `useLLMProviders` for forms that need to:
 *   - Disable LLM-dependent controls when no models are configured.
 *   - Default to the global default text model when the user has not yet
 *     made an explicit choice.
 */
export function useLlmDefaults(): LlmDefaults {
  const { llmProviders, defaultText, defaultVision, isLoading } =
    useLLMProviders();

  const hasAnyLlm = useMemo(
    () =>
      (llmProviders ?? []).some((p) =>
        p.model_configurations.some((m) => m.is_visible)
      ),
    [llmProviders]
  );

  const hasAnyVisionLlm = useMemo(
    () =>
      (llmProviders ?? []).some((p) =>
        p.model_configurations.some(
          (m) => m.is_visible && m.supports_image_input
        )
      ),
    [llmProviders]
  );

  const resolveDefault = useCallback(
    (raw: { provider_id: number; model_name: string } | null) => {
      if (!llmProviders || !raw) return null;
      const provider = llmProviders.find((p) => p.id === raw.provider_id);
      if (!provider) return null;
      if (!provider.name) return null;
      return { providerName: provider.name, modelName: raw.model_name };
    },
    [llmProviders]
  );

  const defaultLlm = useMemo<DefaultLlmReference | null>(
    () => resolveDefault(defaultText),
    [resolveDefault, defaultText]
  );
  const defaultVisionResolved = useMemo<DefaultLlmReference | null>(
    () => resolveDefault(defaultVision),
    [resolveDefault, defaultVision]
  );

  return {
    llmProviders,
    hasAnyLlm,
    hasAnyVisionLlm,
    defaultLlm,
    defaultVision: defaultVisionResolved,
    isLoading,
  };
}
