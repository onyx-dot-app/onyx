"use client";

/**
 * React hooks for embedding model and index settings data.
 *
 * These hooks back the admin Index Settings page and are intentionally
 * separate from `lib/settings/hooks.ts` — they fetch indexing configuration
 * (embedding models, reranking, provider credentials), not application
 * settings like feature flags or UI preferences.
 */

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
 * Determines the SWR `refreshInterval` for the secondary (in-progress)
 * embedding model poll:
 * - 5 s while a migration is in flight (data present)
 * - 60 s otherwise — catches migrations started elsewhere without hammering
 *   the backend when idle
 */
export function secondaryRefreshInterval(
  latestData: EmbeddingModelResponse | null | undefined
): number {
  return latestData ? 5000 : 60000;
}

/**
 * Fetch the active embedding model + search configuration.
 * Polls only when `pollIntervalMs` is provided.
 */
export function useCurrentSearchSettings({
  pollIntervalMs = 0,
}: { pollIntervalMs?: number } = {}) {
  return useSWR<SavedSearchSettings | null>(
    SWR_KEYS.currentSearchSettings,
    errorHandlingFetcher,
    { refreshInterval: pollIntervalMs }
  );
}

/**
 * Fetch the secondary (in-progress) embedding model.
 * Returns `null` when no re-index is running.
 * Self-throttles via `secondaryRefreshInterval`.
 */
export function useSecondarySearchSettings() {
  return useSWR<EmbeddingModelResponse | null>(
    SWR_KEYS.secondarySearchSettings,
    errorHandlingFetcher,
    { refreshInterval: secondaryRefreshInterval }
  );
}

/**
 * Fetch the active embedding model from the current search settings key.
 * Polls only when `pollIntervalMs` is provided.
 *
 * The returned shape does NOT carry a `description` — descriptions are
 * frontend-only. Look them up via `getCurrentModelCopy` if needed.
 */
export function useCurrentEmbeddingModel({
  pollIntervalMs = 0,
}: { pollIntervalMs?: number } = {}) {
  return useSWR<EmbeddingModelResponse | null>(
    SWR_KEYS.currentSearchSettings,
    errorHandlingFetcher,
    { refreshInterval: pollIntervalMs }
  );
}

/**
 * Fetch LLM models available for contextual RAG, including per-model token
 * cost.
 */
export function useLLMContextualCosts() {
  return useSWR<LLMContextualCost[]>(
    SWR_KEYS.llmContextualCost,
    errorHandlingFetcher
  );
}

/**
 * Fetch cloud embedding providers that have credentials configured in the
 * backend.
 *
 * Returns a plain array rather than a `Map` — SWR's internal hash comparison
 * doesn't reliably detect changes between two `Map` instances, which caused
 * stale views after `mutate`. Build a lookup `Map` client-side via `useMemo`
 * if needed.
 */
export function useConfiguredEmbeddingProviders() {
  return useSWR<ConfiguredEmbeddingProvider[]>(
    SWR_KEYS.embeddingProviders,
    errorHandlingFetcher
  );
}
