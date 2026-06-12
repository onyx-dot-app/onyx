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
 * Fetches the active search settings.
 * Polls only when a caller provides `pollIntervalMs`.
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
 * SWR refresh cadence for the secondary settings: 5s while a migration is in
 * flight, 60s otherwise to catch migrations started elsewhere.
 */
export function secondaryRefreshInterval(
  latestData: EmbeddingModelResponse | null | undefined
): number {
  return latestData ? 5000 : 60000;
}

/**
 * Returns the secondary (in-progress) embedding model, or null when no
 * re-index is running. Self-throttles via {@link secondaryRefreshInterval}.
 */
export function useSecondarySearchSettings() {
  return useSWR<EmbeddingModelResponse | null>(
    SWR_KEYS.secondarySearchSettings,
    errorHandlingFetcher,
    { refreshInterval: secondaryRefreshInterval }
  );
}

/**
 * Fetches the active embedding model from the current search settings key.
 * Polls only when a caller provides `pollIntervalMs`.
 *
 * Returns the backend-persisted shape, which does NOT carry a `description`.
 * Descriptions are frontend-only — look them up via `getCurrentModelCopy`.
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
