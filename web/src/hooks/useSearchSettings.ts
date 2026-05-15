"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  ConfiguredEmbeddingProvider,
  EmbeddingModelResponse,
  LLMContextualCost,
  SavedSearchSettings,
} from "@/lib/indexing/interfaces";

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
 * Fetches the FUTURE embedding model, populated only while a
 * switchover is in progress. Returns null when no re-index is running.
 *
 * Polls every 5 seconds so the in-progress banner appears/disappears
 * promptly when the backend transitions states.
 */
export function useSecondarySearchSettings() {
  return useSWR<EmbeddingModelResponse | null>(
    SWR_KEYS.secondarySearchSettings,
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
  return useSWR<EmbeddingModelResponse | null>(
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
    SWR_KEYS.llmContextualCost,
    errorHandlingFetcher
  );
}

/**
 * Fetches cloud embedding providers that have credentials configured in the
 * backend.
 *
 * The fetcher intentionally returns a plain array (and not a `Map`) — SWR's
 * internal hash comparison doesn't reliably detect changes between two `Map`
 * instances, so callers got a stale view after `mutate`. Build a lookup `Map`
 * client-side via `useMemo` if needed.
 */
export function useConfiguredEmbeddingProviders() {
  return useSWR<ConfiguredEmbeddingProvider[]>(
    SWR_KEYS.embeddingProviders,
    errorHandlingFetcher
  );
}
