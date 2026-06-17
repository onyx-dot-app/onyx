"use client";

/**
 * Settings-related React hooks.
 *
 * Two categories:
 *   1. Context readers — `useSettingsContext`, `useVectorDbEnabled`. These
 *      read from the `SettingsContext` that `SettingsProvider` populates.
 *      The vast majority of components use these.
 *   2. Search / embedding fetchers — `useCurrentSearchSettings`,
 *      `useSecondarySearchSettings`, `useCurrentEmbeddingModel`,
 *      `useLLMContextualCosts`, `useConfiguredEmbeddingProviders`. These are
 *      used primarily by the admin Index Settings page.
 *
 * The SWR fetchers that back `SettingsProvider` (`useSettings`,
 * `useEnterpriseSettings`, `useCustomAnalyticsScript`) are private to
 * `providers/SettingsProvider.tsx` and are not exported here.
 */

import { createContext, useContext } from "react";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { CombinedSettings } from "@/interfaces/settings";
import {
  ConfiguredEmbeddingProvider,
  EmbeddingModelResponse,
  LLMContextualCost,
  SavedSearchSettings,
} from "@/lib/indexing/interfaces";

// ─── Settings Context ───────────────────────────────────────────────────────

/**
 * React context that carries the combined application + enterprise settings.
 * Populated by `SettingsProvider` at the root of the app.
 *
 * Consume via `useSettingsContext()` rather than reading this directly —
 * the hook throws a descriptive error when used outside the provider.
 */
export const SettingsContext = createContext<CombinedSettings | null>(null);

// ─── Context-based Hooks ────────────────────────────────────────────────────

/**
 * Access the combined application + enterprise settings from context.
 *
 * Throws if used outside a `SettingsProvider`. This is the primary hook
 * for the vast majority of components — it reads the already-fetched,
 * memoized `CombinedSettings` without triggering any additional network
 * requests.
 *
 * @example
 * const { settings, enterpriseSettings, appName } = useSettingsContext();
 */
export function useSettingsContext() {
  const context = useContext(SettingsContext);
  if (context === null) {
    throw new Error(
      "useSettingsContext must be used within a SettingsProvider"
    );
  }
  return context;
}

/**
 * Returns `true` when the vector database is enabled.
 *
 * Shorthand for `useSettingsContext().settings.vector_db_enabled !== false`.
 * When `DISABLE_VECTOR_DB` is set on the server, connectors, RAG search,
 * document sets, and related features are unavailable.
 */
export function useVectorDbEnabled(): boolean {
  const settings = useSettingsContext();
  return settings.settings.vector_db_enabled !== false;
}

// ─── Search / Embedding Hooks ───────────────────────────────────────────────

/**
 * Determines the SWR `refreshInterval` for the secondary (in-progress)
 * embedding model poll:
 * - 5 s while a migration is in flight (data present)
 * - 60 s otherwise (no migration running — catch migrations started elsewhere)
 */
export function secondaryRefreshInterval(
  latestData: EmbeddingModelResponse | null | undefined
): number {
  return latestData ? 5000 : 60000;
}

/**
 * Fetch the active search / embedding settings.
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
