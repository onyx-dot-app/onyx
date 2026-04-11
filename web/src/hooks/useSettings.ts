import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  Settings,
  EnterpriseSettings,
  ApplicationStatus,
  QueryHistoryType,
} from "@/interfaces/settings";
import { EE_ENABLED } from "@/lib/constants";

// Longer retry delay for critical settings fetches — avoids rapid error→success
// flicker in the SettingsProvider error boundary when there's a transient blip.
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
  temperature_override_enabled: true,
  query_history_type: QueryHistoryType.NORMAL,
} satisfies Settings;

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

  return {
    settings: data ?? DEFAULT_SETTINGS,
    isLoading,
    error,
  };
}

export function useEnterpriseSettings(eeEnabledRuntime: boolean): {
  enterpriseSettings: EnterpriseSettings | null;
  isLoading: boolean;
  error: Error | undefined;
} {
  // Gate on the build-time flag OR the runtime ee_features_enabled from
  // /api/settings. The build-time flag (NEXT_PUBLIC_ENABLE_PAID_EE_FEATURES)
  // may be unset even when the server enables EE via LICENSE_ENFORCEMENT_ENABLED,
  // so the runtime check is needed as a fallback.
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
      // Referential equality instead of SWR's default deep comparison.
      // The logo image can change without the settings JSON changing
      // (same use_custom_logo: true), so we need every mutate() call
      // to propagate a new reference so cache-busters recalculate.
      compare: (a, b) => a === b,
    }
  );

  return {
    enterpriseSettings: data ?? null,
    isLoading: shouldFetch ? isLoading : false,
    error,
  };
}

export function useCustomAnalyticsScript(
  eeEnabledRuntime: boolean
): string | null {
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
