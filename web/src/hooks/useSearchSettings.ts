import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  EmbeddingModelDescriptor,
  EmbeddingProvider,
  LLMContextualCost,
  SavedSearchSettings,
} from "@/lib/indexing/interfaces";
import { EMBEDDING_PROVIDERS_ADMIN_URL } from "@/lib/indexing";
import { LLM_CONTEXTUAL_COST_ADMIN_URL } from "@/lib/llmConfig/constants";

/**
 * Fetches the currently-active search settings, including the embedding model
 * configuration and advanced retrieval options.
 *
 * Polls every 5 seconds so the UI stays in sync with backend-side changes
 * (e.g. embedding migration completion).
 */
export function useCurrentSearchSettings() {
  return useSWR<SavedSearchSettings | null>(
    SWR_KEYS.currentSearchSettings,
    errorHandlingFetcher,
    { refreshInterval: 5000 }
  );
}

/**
 * Fetches the currently-active embedding model. Narrower-typed view of
 * {@link useCurrentSearchSettings} focused on model metadata (name,
 * provider, etc.).
 *
 * Returns the backend-persisted shape, which does NOT carry a `description`.
 * Descriptions are frontend-only — look them up via `getCurrentModelCopy`.
 */
export function useCurrentEmbeddingModel() {
  return useSWR<EmbeddingModelDescriptor | null>(
    SWR_KEYS.currentSearchSettings,
    errorHandlingFetcher,
    { refreshInterval: 5000 }
  );
}

/**
 * Fetches the list of LLM models available for contextual RAG, including
 * per-model token cost.
 */
export function useLLMContextualCosts() {
  return useSWR<LLMContextualCost[]>(
    LLM_CONTEXTUAL_COST_ADMIN_URL,
    errorHandlingFetcher
  );
}

/**
 * Fetches the secondary (FUTURE) search settings — the model the admin has
 * selected as the next embedding model. Returns `null` when no switch is
 * pending.
 *
 * Polls every 5 seconds to stay in sync with backend state.
 */
export function useSecondarySearchSettings() {
  return useSWR<EmbeddingModelDescriptor | null>(
    "/api/search-settings/get-secondary-search-settings",
    errorHandlingFetcher,
    { refreshInterval: 5000 }
  );
}

/**
 * Fetches the set of cloud embedding provider types that have API keys
 * configured in the backend.
 */
export function useConfiguredEmbeddingProviders() {
  return useSWR<Set<EmbeddingProvider>>(
    EMBEDDING_PROVIDERS_ADMIN_URL,
    async (url: string) => {
      const providers: { provider_type: EmbeddingProvider }[] =
        await errorHandlingFetcher(url);
      return new Set(providers.map((p) => p.provider_type));
    }
  );
}
