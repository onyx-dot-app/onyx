"use client";

import { CombinedSettings } from "@/interfaces/settings";
import {
  createContext,
  useContext,
  useEffect,
  useState,
  useMemo,
  JSX,
} from "react";
import useCCPairs from "@/hooks/useCCPairs";
import {
  useSettings,
  useEnterpriseSettings,
  useCustomAnalyticsScript,
} from "@/hooks/useSettings";
import { HOST_URL, NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import CloudError from "@/components/errorPages/CloudErrorPage";
import ErrorPage from "@/components/errorPages/ErrorPage";
import { FetchError } from "@/lib/fetcher";

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
    !coreSettingsLoading && settings.vector_db_enabled !== false;
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

export const SettingsContext = createContext<CombinedSettings | null>(null);

export function useSettingsContext() {
  const context = useContext(SettingsContext);
  if (context === null) {
    throw new Error(
      "useSettingsContext must be used within a SettingsProvider"
    );
  }
  return context;
}

export function useVectorDbEnabled(): boolean {
  const settings = useSettingsContext();
  return settings.settings.vector_db_enabled !== false;
}
