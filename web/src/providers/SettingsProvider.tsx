"use client";

import { useSettings } from "@/lib/settings/hooks";
import { AuthLayouts } from "@opal/layouts";
import { NEXT_PUBLIC_CLOUD_ENABLED, DOCS_BASE_URL } from "@/lib/constants";
import { FetchError } from "@/lib/fetcher";
import { welcomeCardCopy } from "@/lib/auth/copies";
import { getAppLogo } from "@/lib/app/utils";
import { markdown } from "@opal/utils";

interface SettingsProviderProps {
  children: React.ReactNode;
}

/**
 * Renders a fatal error page when core or enterprise settings cannot be
 * fetched. Auth errors (401/403) are expected on the login page and are
 * silently ignored so unauthenticated users still see the app shell.
 */
export default function SettingsProvider({ children }: SettingsProviderProps) {
  const { appName, logoUrl, error } = useSettings();

  function isAuthError(err: Error) {
    return (
      err instanceof FetchError && (err.status === 401 || err.status === 403)
    );
  }

  if (error && !isAuthError(error)) {
    return (
      <AuthLayouts.Root>
        <AuthLayouts.Card
          {...welcomeCardCopy(appName)}
          icon={getAppLogo(logoUrl)}
        >
          {NEXT_PUBLIC_CLOUD_ENABLED ? (
            <AuthLayouts.Message
              title="Maintenance in progress."
              description={markdown(
                "Onyx is currently under scheduled maintenance. Please check back later. [Contact support](mailto:support@onyx.app)"
              )}
            />
          ) : (
            <AuthLayouts.Message
              messageType="warning"
              title="Unable to load settings"
              description={markdown(
                `If you're an admin, please review our [documentation](${DOCS_BASE_URL}?utm_source=app&utm_medium=error_page&utm_campaign=config_error) for proper configuration steps. If you're a user, please contact your admin for assistance.`,
                "Need help? Join our [Discord community](https://discord.gg/4NA5SbzrWb) for support."
              )}
            />
          )}
        </AuthLayouts.Card>
      </AuthLayouts.Root>
    );
  }

  return children;
}
