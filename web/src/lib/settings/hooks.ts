"use client";

/**
 * Application settings hooks.
 *
 * All hooks here are SWR-backed — SWR deduplicates by key, so multiple
 * components calling the same hook trigger only one network request.
 *
 * Prefer calling the specific hook your component needs rather than a combined
 * accessor — it makes the data dependency explicit and avoids pulling in
 * unrelated settings.
 */

import useSWR from "swr";
import useCCPairs from "@/hooks/useCCPairs";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  ApplicationStatus,
  EnterpriseSettings,
  QueryHistoryType,
  Settings,
} from "@/lib/settings/types";
import { EE_ENABLED } from "@/lib/constants";

// ─── Internal constants ─────────────────────────────────────────────────────

// Longer retry delay — avoids rapid error→success flicker in the error
// boundary during transient backend blips.
const SETTINGS_ERROR_RETRY_INTERVAL = 5_000;

export const DEFAULT_SETTINGS = {
  auto_scroll: true,
  application_status: ApplicationStatus.ACTIVE,
  gpu_enabled: false,
  maximum_chat_retention_days: null,
  notifications: [],
  needs_reindexing: false,
  anonymous_user_enabled: false,
  invite_only_enabled: false,
  deep_research_enabled: true,
  multi_model_chat_enabled: true,
  temperature_override_enabled: true,
  query_history_type: QueryHistoryType.NORMAL,
} satisfies Settings;

// ─── SWR-backed hooks ───────────────────────────────────────────────────────

/**
 * Fetch core application settings from `/api/settings`.
 *
 * Falls back to `DEFAULT_SETTINGS` while loading so callers always receive a
 * valid `Settings` object (never `undefined`).
 */
export function useSettings(): {
  settings: Settings;
  isLoading: boolean;
  error: Error | undefined;
} {
  const { data, error, isLoading } = useSWR<Settings>(
    SWR_KEYS.settings,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      revalidateIfStale: false,
      dedupingInterval: 30_000,
      errorRetryInterval: SETTINGS_ERROR_RETRY_INTERVAL,
    }
  );
  return { settings: data ?? DEFAULT_SETTINGS, isLoading, error };
}

/**
 * Fetch enterprise-specific settings from `/api/enterprise-settings`.
 *
 * Self-gated: calls `useSettings()` internally to determine whether the
 * backend has EE enabled before fetching, so callers don't need to manage the
 * gating themselves.
 */
export function useEnterpriseSettings(): {
  enterpriseSettings: EnterpriseSettings | null;
  isLoading: boolean;
  error: Error | undefined;
} {
  const { settings, isLoading: coreLoading, error: coreError } = useSettings();
  const shouldFetch =
    EE_ENABLED ||
    (!coreLoading && !coreError && settings.ee_features_enabled !== false);

  const { data, error, isLoading } = useSWR<EnterpriseSettings>(
    shouldFetch ? SWR_KEYS.enterpriseSettings : null,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      revalidateIfStale: false,
      dedupingInterval: 30_000,
      errorRetryInterval: SETTINGS_ERROR_RETRY_INTERVAL,
      // Referential equality instead of SWR's default deep compare.
      // Logo can change without the JSON changing (same use_custom_logo: true),
      // so mutate() must propagate a new reference for cache-busters.
      compare: (a, b) => a === b,
    }
  );
  return {
    enterpriseSettings: data ?? null,
    isLoading: shouldFetch ? isLoading : false,
    error,
  };
}

/**
 * Fetch the custom analytics script string from
 * `/api/enterprise-settings/custom-analytics-script`.
 *
 * Returns `null` when EE is disabled or no script is configured. Self-gated
 * on EE availability (same logic as `useEnterpriseSettings`).
 */
export function useCustomAnalyticsScript(): string | null {
  const { settings, isLoading: coreLoading, error: coreError } = useSettings();
  const shouldFetch =
    EE_ENABLED ||
    (!coreLoading && !coreError && settings.ee_features_enabled !== false);

  const { data } = useSWR<string>(
    shouldFetch ? SWR_KEYS.customAnalyticsScript : null,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      revalidateIfStale: false,
      dedupingInterval: 60_000,
    }
  );
  return data ?? null;
}

// ─── Derived hooks ──────────────────────────────────────────────────────────

/**
 * Resolved application display name.
 *
 * Returns `enterpriseSettings.application_name` when set, otherwise `"Onyx"`.
 * Always returns a non-empty string — safe to use without a null check.
 */
export function useAppName(): string {
  const { enterpriseSettings } = useEnterpriseSettings();
  return enterpriseSettings?.application_name?.trim() || "Onyx";
}

/**
 * Returns `true` when the vector database is enabled.
 *
 * When `DISABLE_VECTOR_DB` is set on the server, connectors, RAG search,
 * document sets, and related features are unavailable.
 */
export function useVectorDbEnabled(): boolean {
  const { settings, isLoading, error } = useSettings();
  return !isLoading && !error && settings.vector_db_enabled !== false;
}

/**
 * Returns `true` when search mode is actually usable by the current user.
 *
 * Combines the admin's `search_ui_enabled` preference with the runtime
 * prerequisite that at least one connector is configured. Prefer this over
 * reading `settings.search_ui_enabled` directly.
 */
export function useIsSearchModeAvailable(): boolean {
  const { settings, isLoading, error } = useSettings();
  const vectorDbEnabled =
    !isLoading && !error && settings.vector_db_enabled !== false;
  const { ccPairs } = useCCPairs(vectorDbEnabled);
  return settings.search_ui_enabled !== false && ccPairs.length > 0;
}
