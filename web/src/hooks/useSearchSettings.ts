import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  EmbeddingModelDescriptor,
  LLMContextualCost,
  SavedSearchSettings,
} from "@/lib/indexing/interfaces";
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
 * Fetches the embedding model for an in-progress migration. Non-null while
 * an embedding model switchover is running.
 */
export function useFutureEmbeddingModel() {
  return useSWR<EmbeddingModelDescriptor | null>(
    SWR_KEYS.secondarySearchSettings,
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
