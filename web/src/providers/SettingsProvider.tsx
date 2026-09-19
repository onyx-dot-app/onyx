"use client";

import { JSX } from "react";
import { useSettings } from "@/lib/settings/hooks";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import CloudError from "@/components/errorPages/CloudErrorPage";
import ErrorPage from "@/components/errorPages/ErrorPage";
import { FetchError } from "@/lib/fetcher";

/**
 * Renders a fatal error page when core or enterprise settings cannot be
 * fetched. Auth errors (401/403) are expected on the login page and are
 * silently ignored so unauthenticated users still see the app shell.
 */
export function SettingsProvider({
  children,
}: {
  children: React.ReactNode | JSX.Element;
}) {
  const { error } = useSettings();

  const isAuthError = (err: Error | undefined) =>
    err instanceof FetchError && (err.status === 401 || err.status === 403);

  if (error && !isAuthError(error)) {
    return NEXT_PUBLIC_CLOUD_ENABLED ? <CloudError /> : <ErrorPage />;
  }

  return <>{children}</>;
}
