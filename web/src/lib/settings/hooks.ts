"use client";

import useSWR from "swr";
import { useMemo } from "react";
import useCCPairs from "@/hooks/useCCPairs";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  ApplicationStatus,
  AppSettings,
  EnterpriseSettings,
  QueryHistoryType,
  Settings,
} from "@/lib/settings/types";
import { EE_ENABLED } from "@/lib/constants";

const SETTINGS_ERROR_RETRY_INTERVAL = 5_000;

const DEFAULT_SETTINGS: Settings = {
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
};

/**
 * The single settings hook. Returns a fully-derived `AppSettings` object that
 * merges core settings and enterprise settings into one consistent shape.
 *
 * Derived fields (`appName`, `vectorDbEnabled`) are pre-computed so callers
 * never have to re-derive them or fetch enterprise settings separately.
 */
export function useSettings(): AppSettings {
  const {
    data: rawSettings,
    error: settingsError,
    isLoading: settingsLoading,
  } = useSWR<Settings>(SWR_KEYS.settings, errorHandlingFetcher, {
    revalidateOnFocus: false,
    revalidateOnReconnect: false,
    revalidateIfStale: false,
    dedupingInterval: 30_000,
    errorRetryInterval: SETTINGS_ERROR_RETRY_INTERVAL,
  });

  const core = rawSettings ?? DEFAULT_SETTINGS;
  const shouldFetchEnterprise =
    EE_ENABLED ||
    (!settingsLoading && !settingsError && core.ee_features_enabled !== false);

  const {
    data: enterprise,
    error: enterpriseError,
    isLoading: enterpriseLoading,
  } = useSWR<EnterpriseSettings>(
    shouldFetchEnterprise ? SWR_KEYS.enterpriseSettings : null,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      revalidateIfStale: false,
      dedupingInterval: 30_000,
      errorRetryInterval: SETTINGS_ERROR_RETRY_INTERVAL,
      // Referential equality — logo can change without JSON changing, so
      // mutate() must propagate a new reference for cache-busters.
      compare: (a, b) => a === b,
    }
  );

  // Cache-buster: the logo endpoint URL never changes, so the browser serves
  // a cached image even after an admin uploads a new logo. Regenerating this
  // timestamp whenever the enterprise settings reference changes forces a
  // re-fetch. We use referential equality on the SWR data (compare: a===b),
  // so this only fires when SWR actually receives new enterprise data.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const logoBuster = useMemo(() => Date.now(), [enterprise]);

  return {
    ...core,
    enterprise: enterprise ?? null,
    appName: enterprise?.application_name?.trim() || "Onyx",
    logoUrl: enterprise?.use_custom_logo
      ? `/api/enterprise-settings/logo?v=${logoBuster}`
      : null,
    vectorDbEnabled:
      !settingsLoading && !settingsError && core.vector_db_enabled !== false,
    isLoading:
      settingsLoading || (shouldFetchEnterprise ? enterpriseLoading : false),
    error: settingsError ?? enterpriseError,
  };
}

/**
 * Returns `true` when search mode is actually usable by the current user.
 *
 * This is a cross-cutting hook: it joins `useSettings()` (two settings
 * endpoints) with connector state (`useCCPairs`). It is intentionally kept
 * separate from `useSettings()` so that the connector list fetch only fires in
 * the small number of components that actually need it.
 */
export function useIsSearchModeAvailable(): boolean {
  const { vectorDbEnabled, search_ui_enabled } = useSettings();
  const { ccPairs } = useCCPairs(vectorDbEnabled);
  return search_ui_enabled !== false && ccPairs.length > 0;
}
