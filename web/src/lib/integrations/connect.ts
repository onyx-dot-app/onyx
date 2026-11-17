import { loadPage } from "@opal/navigation";
import { launchOAuth, OAuthLaunchError } from "@/lib/oauth/launch";
import { startUserOAuth } from "@/lib/integrations/svc";
import type { MemberIntegration } from "@/lib/integrations/types";

/** What a member does to fix the connection, or null when there is nothing to do. */
export type ConnectAction = "connect" | "reconnect" | null;

export function connectAction(integration: MemberIntegration): ConnectAction {
  if (
    integration.status.moving_credentials ||
    (integration.auth_method !== "oauth2" &&
      integration.auth_method !== "api_key")
  )
    return null;
  if (integration.status.state === "not_connected") return "connect";
  if (integration.status.state === "needs_reconnect") return "reconnect";
  return null;
}

/**
 * Runs the user's OAuth sign-in in a new tab and resolves when the callback
 * page reports. When the browser blocks the tab, the sign-in continues in
 * this tab and the callback returns to `returnPath`; the result is then
 * "redirected".
 */
export async function connectWithOAuth(
  integrationId: number,
  returnPath: string
): Promise<"connected" | "redirected"> {
  try {
    await launchOAuth(() => startUserOAuth(integrationId, returnPath));
    return "connected";
  } catch (error) {
    if (
      !(error instanceof OAuthLaunchError) ||
      error.reason !== "popup_blocked"
    )
      throw error;
    loadPage(await startUserOAuth(integrationId, returnPath));
    return "redirected";
  }
}
