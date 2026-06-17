"use client";

import {
  ApplicationStatus,
  CombinedSettings,
  EnterpriseSettings,
  QueryHistoryType,
  Settings,
} from "@/interfaces/settings";
import { useEffect, useState, useMemo, JSX } from "react";
import useSWR from "swr";
import useCCPairs from "@/hooks/useCCPairs";
import { SettingsContext } from "@/lib/settings/hooks";
import {
  EE_ENABLED,
  HOST_URL,
  NEXT_PUBLIC_CLOUD_ENABLED,
} from "@/lib/constants";
import CloudError from "@/components/errorPages/CloudErrorPage";
import ErrorPage from "@/components/errorPages/ErrorPage";
import { errorHandlingFetcher, FetchError } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";

// Longer retry delay for settings fetches — avoids rapid error→success flicker
// in the error boundary during transient backend blips.
const SETTINGS_ERROR_RETRY_INTERVAL = 5_000;

const DEFAULT_SETTINGS = {
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

function useSettings(): {
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

function useEnterpriseSettings(eeEnabledRuntime: boolean): {
  enterpriseSettings: EnterpriseSettings | null;
  isLoading: boolean;
  error: Error | undefined;
} {
  const shouldFetch = EE_ENABLED || eeEnabledRuntime;
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

function useCustomAnalyticsScript(eeEnabledRuntime: boolean): string | null {
  const shouldFetch = EE_ENABLED || eeEnabledRuntime;
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

export function SettingsProvider({
  children,
}: {
  children: React.ReactNode | JSX.Element;
}) {
  const {
    settings,
    isLoading: coreSettingsLoading,
    error: settingsError,
  } = useSettings();

  // Once core settings load, check if the backend reports EE as enabled.
  // This handles deployments where NEXT_PUBLIC_ENABLE_PAID_EE_FEATURES is
  // unset but LICENSE_ENFORCEMENT_ENABLED defaults to true on the server.
  const eeEnabledRuntime =
    !coreSettingsLoading &&
    !settingsError &&
    settings.ee_features_enabled !== false;

  const {
    enterpriseSettings,
    isLoading: enterpriseSettingsLoading,
    error: enterpriseSettingsError,
  } = useEnterpriseSettings(eeEnabledRuntime);
  const customAnalyticsScript = useCustomAnalyticsScript(eeEnabledRuntime);

  const [isMobile, setIsMobile] = useState<boolean | undefined>();
  const settingsLoading = coreSettingsLoading || enterpriseSettingsLoading;
  const vectorDbEnabled =
    !coreSettingsLoading &&
    !settingsError &&
    settings.vector_db_enabled !== false;
  const { ccPairs } = useCCPairs(vectorDbEnabled);

  useEffect(() => {
    const checkMobile = () => {
      setIsMobile(window.innerWidth < 768);
    };

    checkMobile();
    window.addEventListener("resize", checkMobile);
    return () => window.removeEventListener("resize", checkMobile);
  }, []);

  /**
   * NOTE (@raunakab):
   * Whether search mode is actually available to users.
   *
   * Prefer `isSearchModeAvailable` over `settings.search_ui_enabled`.
   * The raw setting only captures the admin's *intent*. This derived value
   * also checks runtime prerequisites (connectors must exist) so that
   * consumers don't need to independently verify availability.
   */
  const isSearchModeAvailable = useMemo(
    () => settings.search_ui_enabled !== false && ccPairs.length > 0,
    [settings.search_ui_enabled, ccPairs.length]
  );

  const combinedSettings: CombinedSettings = useMemo(
    () => ({
      settings,
      enterpriseSettings,
      customAnalyticsScript,
      webVersion: settings.version ?? null,
      webDomain: HOST_URL,
      isMobile,
      isSearchModeAvailable,
      settingsLoading,
      appName: enterpriseSettings?.application_name?.trim() || "Onyx",
    }),
    [
      settings,
      enterpriseSettings,
      customAnalyticsScript,
      isMobile,
      isSearchModeAvailable,
      settingsLoading,
    ]
  );

  // Auth errors (401/403) are expected for unauthenticated users (e.g. login
  // page). Fall through with default settings so the app can render normally.
  const isAuthError = (err: Error | undefined) =>
    err instanceof FetchError && (err.status === 401 || err.status === 403);

  const hasFatalError =
    (settingsError && !isAuthError(settingsError)) ||
    (enterpriseSettingsError && !isAuthError(enterpriseSettingsError));

  if (hasFatalError) {
    return NEXT_PUBLIC_CLOUD_ENABLED ? <CloudError /> : <ErrorPage />;
  }

  return (
    <SettingsContext.Provider value={combinedSettings}>
      {children}
    </SettingsContext.Provider>
  );
}
