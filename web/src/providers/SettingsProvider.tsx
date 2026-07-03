"use client";

import { useSettings } from "@/lib/settings/hooks";
import { AuthLayouts } from "@opal/layouts";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import MaintenanceCard from "@/sections/errorCards/MaintenanceCard";
import ErrorCard from "@/sections/errorCards/ErrorCard";
import { FetchError } from "@/lib/fetcher";

interface SettingsProviderProps {
  children: React.ReactNode;
}

/**
 * Renders a fatal error page when core or enterprise settings cannot be
 * fetched. Auth errors (401/403) are expected on the login page and are
 * silently ignored so unauthenticated users still see the app shell.
 */
export default function SettingsProvider({ children }: SettingsProviderProps) {
  const { error } = useSettings();

  function isAuthError(err: Error | undefined) {
    return (
      err instanceof FetchError && (err.status === 401 || err.status === 403)
    );
  }

  if (error && !isAuthError(error)) {
    return (
      <AuthLayouts.Root>
        {NEXT_PUBLIC_CLOUD_ENABLED ? <MaintenanceCard /> : <ErrorCard />}
      </AuthLayouts.Root>
    );
  }

  return children;
}
