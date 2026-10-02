"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import useSWR, { type KeyedMutator } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { isAuthPath } from "@/lib/auth/paths";
import { useActiveAgent } from "@/lib/agents/hooks";
import {
  LLMProviderDescriptor,
  LLMProviderName,
  LLMProviderResponse,
  LLMProviderView,
  ModelConfiguration,
  WellKnownLLMProviderDescriptor,
} from "@/lib/languageModels/types";
import type {
  CustomProviderOption,
  DefaultLlmReference,
  LlmDefaults,
  ModelConfigurationPage,
  ModelPaging,
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

type RawModelConfigurationPage = Omit<
  ModelConfigurationPage,
  "model_configurations"
> & { model_configurations: RawModelConfiguration[] };

type ModelPageParams = { offset: number; query?: string };

/** Where the next window of a search's matches starts, per provider. */
type SearchWindows = {
  query: string;
  nextOffsets: Record<number, number | null>;
};

/** What model paging reads off a listed provider, admin view or descriptor. */
type PageableProvider = {
  id: number;
  model_configurations: RawModelConfiguration[];
  next_model_configuration_offset?: number | null;
};

// ---------------------------------------------------------------------------
// Model paging helpers
// ---------------------------------------------------------------------------

/** True while the listing holds only part of the provider's models. */
function hasUnloadedModels(provider: PageableProvider): boolean {
  return provider.next_model_configuration_offset != null;
}

function fetchModelConfigurationPage(
  providerId: number,
  agentId: number | undefined,
  params: ModelPageParams
): Promise<RawModelConfigurationPage> {
  const search = new URLSearchParams({ offset: String(params.offset) });
  if (params.query !== undefined) search.set("query", params.query);
  if (agentId !== undefined) search.set("persona_id", String(agentId));
  return errorHandlingFetcher<RawModelConfigurationPage>(
    `${SWR_KEYS.llmProviderModels(providerId)}?${search}`
  );
}

/** The listing with one provider's page appended, deduplicated by id. Only
 *  an offset page moves the provider's next offset. */
function mergeModelConfigurationPage<P extends PageableProvider>(
  response: LLMProviderResponse<P>,
  providerId: number,
  page: RawModelConfigurationPage,
  params: ModelPageParams
): LLMProviderResponse<P> {
  const provider = response.providers.find((p) => p.id === providerId);
  if (!provider) return response;
  const loadedIds = new Set(provider.model_configurations.map((mc) => mc.id));
  const added = page.model_configurations.filter((mc) => !loadedIds.has(mc.id));
  const nextOffset =
    params.query === undefined
      ? page.next_offset
      : provider.next_model_configuration_offset;
  if (
    added.length === 0 &&
    nextOffset === provider.next_model_configuration_offset
  ) {
    return response;
  }
  const merged: P = {
    ...provider,
    model_configurations: [...provider.model_configurations, ...added],
    next_model_configuration_offset: nextOffset,
  };
  return {
    ...response,
    providers: response.providers.map((p) => (p === provider ? merged : p)),
  };
}

/**
 * The `ModelPaging` over a cached provider listing: pages and server searches
 * merge into that listing through `mutate`, so every reader of it sees the
 * new models. `agentId` scopes the page requests like the listing itself.
 */
function useModelPaging<P extends PageableProvider>(
  raw: LLMProviderResponse<P> | undefined,
  mutate: KeyedMutator<LLMProviderResponse<P>>,
  agentId?: number
): ModelPaging {
  // One page request at a time, later calls are dropped: a scroll burst or
  // keystroke storm must not fan out into parallel fetches.
  const pageInFlightRef = useRef(false);
  const [isLoadingPage, setIsLoadingPage] = useState(false);
  const applyModelPage = useCallback(
    async (
      providerId: number,
      params: ModelPageParams
    ): Promise<RawModelConfigurationPage | null> => {
      if (pageInFlightRef.current) return null;
      pageInFlightRef.current = true;
      setIsLoadingPage(true);
      try {
        const page = await fetchModelConfigurationPage(
          providerId,
          agentId,
          params
        );
        await mutate(
          (current) =>
            current &&
            mergeModelConfigurationPage(current, providerId, page, params),
          { revalidate: false }
        );
        return page;
      } finally {
        pageInFlightRef.current = false;
        setIsLoadingPage(false);
      }
    },
    [agentId, mutate]
  );

  const truncatedProviders = useMemo(
    () => raw?.providers.filter(hasUnloadedModels) ?? [],
    [raw]
  );
  const [searchWindows, setSearchWindows] = useState<SearchWindows | null>(
    null
  );
  return useMemo<ModelPaging>(
    () => ({
      hasMore: truncatedProviders.length > 0,
      isLoading: isLoadingPage,
      loadMore: async (providerIds?: number[]) => {
        const provider =
          providerIds === undefined
            ? truncatedProviders[0]
            : providerIds
                .map((id) => truncatedProviders.find((p) => p.id === id))
                .find((p) => p !== undefined);
        if (provider?.next_model_configuration_offset == null) return;
        await applyModelPage(provider.id, {
          offset: provider.next_model_configuration_offset,
        });
      },
      search: async (query: string, providerIds?: number[]) => {
        const searched =
          providerIds === undefined
            ? truncatedProviders
            : truncatedProviders.filter((p) => providerIds.includes(p.id));
        const nextOffsets: Record<number, number | null> = {};
        for (const provider of searched) {
          const page = await applyModelPage(provider.id, { offset: 0, query });
          if (page === null) return false;
          nextOffsets[provider.id] = page.next_offset;
        }
        setSearchWindows({ query, nextOffsets });
        return true;
      },
      searchHasMore:
        searchWindows !== null &&
        Object.values(searchWindows.nextOffsets).some((o) => o !== null),
      loadMoreSearch: async () => {
        if (searchWindows === null) return;
        const next = Object.entries(searchWindows.nextOffsets).find(
          ([, offset]) => offset !== null
        );
        if (next === undefined || next[1] === null) return;
        const providerId = Number(next[0]);
        const page = await applyModelPage(providerId, {
          offset: next[1],
          query: searchWindows.query,
        });
        if (page === null) return;
        setSearchWindows({
          query: searchWindows.query,
          nextOffsets: {
            ...searchWindows.nextOffsets,
            [providerId]: page.next_offset,
          },
        });
      },
    }),
    [truncatedProviders, isLoadingPage, applyModelPage, searchWindows]
  );
}

/** A keystroke storm settles before a search leaves for the server. */
export const SERVER_SEARCH_DEBOUNCE_MS = 300;

/** Asks the server for `query` once it settles, while `enabled`, and says
 *  whether the current query is answered, which gates paging its matches. A
 *  merged page re-runs nothing, and a skipped search retries once it can. */
export function useServerModelSearch(
  modelPaging: ModelPaging | undefined,
  query: string,
  enabled: boolean,
  providerIds?: number[]
): boolean {
  const [answeredQuery, setAnsweredQuery] = useState("");
  const currentQueryRef = useRef("");
  useEffect(() => {
    currentQueryRef.current = query;
    if (query === "") {
      // A cleared search forgets its answer, so the next one runs even after
      // a listing refresh dropped the merged matches.
      setAnsweredQuery("");
      return;
    }
    if (!modelPaging || !enabled || answeredQuery === query) return;
    const handle = setTimeout(() => {
      modelPaging
        .search(query, providerIds)
        .then((searched) => {
          // A search that lands after its query changed is not remembered.
          if (searched && currentQueryRef.current === query) {
            setAnsweredQuery(query);
          }
        })
        .catch(console.error);
    }, SERVER_SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [modelPaging, query, enabled, answeredQuery, providerIds]);
  return query !== "" && answeredQuery === query;
}

// ---------------------------------------------------------------------------
// Enrichment, private helpers
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
 * The user-scoped provider request behind the public list hooks. Private:
 * callers pick a named hook below so the list they get is in the name.
 *
 * Hits the **non-admin** endpoints which return `LLMProviderDescriptor`
 * (no `id` or sensitive fields like `api_key`):
 * - No `agentId` → `GET /api/llm/provider`, all public providers plus
 *   restricted providers the user can access via group membership.
 * - With `agentId` → `GET /api/llm/persona/{agentId}/providers`, providers
 *   scoped to that agent, respecting RBAC restrictions.
 *
 * The backend wraps the provider list in an `LLMProviderResponse` envelope
 * that also carries the global defaults. Those are exposed as returned.
 */
function useLanguageModelsRequest(agentId?: number) {
  // No chat on /auth/* routes, where an unauthenticated caller would 403.
  const onAuthPath = isAuthPath(usePathname());
  const url = onAuthPath
    ? null
    : agentId !== undefined
      ? SWR_KEYS.llmProvidersForAgent(agentId)
      : SWR_KEYS.llmProviders;

  // `revalidateIfStale` is intentionally left at its default (true), unlike
  // `useAdminLanguageModels` below. Admin edits call `refreshLlmProviderCaches`,
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
  const modelPaging = useModelPaging(raw, mutate, agentId);

  return {
    llmProviders: data?.providers,
    defaultText: data?.default_text ?? null,
    defaultVision: data?.default_vision ?? null,
    defaultChatNaming: data?.default_chat_naming ?? null,
    defaultCraft: data?.default_craft ?? null,
    isLoading: !error && !data,
    error,
    modelPaging,
    // `mutate` resolves to the raw (unenriched) response, so callers must not
    // read its result. Wrapping it keeps the revalidation without the lie.
    refetch: async (): Promise<void> => {
      await mutate();
    },
  };
}

/** Every provider the current user may use, with its first page of models. */
export function useLanguageModels() {
  return useLanguageModelsRequest();
}

/**
 * The providers this agent may use. A new agent has no id yet, so
 * `undefined` falls back to the unscoped list.
 */
export function useLanguageModelsForAgent(agentId: number | undefined) {
  return useLanguageModelsRequest(agentId);
}

/**
 * The user's providers trimmed to visible models that accept image input,
 * for captioning and other vision-only pickers. Providers left with no
 * such model are dropped.
 */
export function useVisionLanguageModels() {
  const result = useLanguageModelsRequest();
  const llmProviders = useMemo(
    () =>
      result.llmProviders
        ?.map((provider) => ({
          ...provider,
          model_configurations: provider.model_configurations.filter(
            (mc) => mc.is_visible && mc.supports_image_input
          ),
        }))
        .filter((provider) => provider.model_configurations.length > 0),
    [result.llmProviders]
  );
  return { ...result, llmProviders };
}

/**
 * Resolves the active agent via `useActiveAgent` and fetches that agent's
 * providers. User-facing model UIs (chat model selectors, popovers)
 * consistently need exactly this pairing, so this hook keeps the resolution
 * in one place instead of repeating it at each call site.
 */
export function useLanguageModelsForCurrentAgent() {
  const activeAgent = useActiveAgent();
  // Scoped to the Assistant too. The endpoint answers "which providers may this
  // user use with this agent", and the Assistant can carry restrictions like
  // any other, so the unscoped list would over-report them.
  return useLanguageModelsRequest(activeAgent?.id);
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
 * — use `useLanguageModels` instead.
 *
 * @returns
 * - `llmProviders`: Provider views carrying each provider's first page of
 *    models (see `next_model_configuration_offset`) until `modelPaging` loads
 *    more, or `undefined` while loading.
 * - `modelPaging`: pages and searches the rest into `llmProviders`, for the
 *    admin model pickers and the provider edit modal.
 * - `defaultText` — The global default text model.
 * - `defaultVision` — The global default vision model.
 * - `defaultCraft`: the admin-configured default Craft model, or `null` if
 *    unset. Craft then falls back to `defaultText`.
 * - `isLoading` — `true` until the first successful response or error.
 * - `error` — The SWR error object, if any.
 * - `refetch` — SWR `mutate` function to trigger a revalidation.
 */
export function useAdminLanguageModels() {
  const {
    data: raw,
    error,
    mutate,
  } = useSWR<LLMProviderResponse<RawLLMProviderView>>(
    SWR_KEYS.adminLlmProvidersPaged,
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
  const modelPaging = useModelPaging(raw, mutate);

  return {
    llmProviders: data?.providers,
    defaultText: data?.default_text ?? null,
    defaultVision: data?.default_vision ?? null,
    defaultChatNaming: data?.default_chat_naming ?? null,
    defaultCraft: data?.default_craft ?? null,
    isLoading: !error && !data,
    error,
    modelPaging,
    refetch: mutate,
  };
}

/** One provider with every model, for the custom editor whose own model
 *  table has no paging and whose PUT replaces the list. */
export function useAdminLanguageModel(providerId: number | null) {
  const {
    data: raw,
    error,
    isLoading,
  } = useSWR<RawLLMProviderView>(
    providerId === null ? null : SWR_KEYS.adminLlmProvider(providerId),
    errorHandlingFetcher,
    { revalidateOnFocus: false }
  );

  const llmProvider = useMemo(
    () => (raw ? enrichViews([raw])[0] : undefined),
    [raw]
  );

  return { llmProvider, isLoading, error };
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

/**
 * Derived view over `useLanguageModels` for forms that need to:
 *   - Disable LLM-dependent controls when no models are configured.
 *   - Default to the global default text model when the user has not yet
 *     made an explicit choice.
 */
export function useLlmDefaults(): LlmDefaults {
  const { llmProviders, defaultText, defaultVision, isLoading } =
    useLanguageModels();

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
      // No name check: well-known providers are routinely saved with a null
      // name, and dropping those defaults left the admin pickers showing
      // nothing for a model that was in fact configured.
      return {
        providerId: provider.id,
        modelName: raw.model_name,
      };
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
