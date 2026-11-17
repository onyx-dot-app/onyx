import type { ErrorResponseBody } from "@/lib/fetcher";
import { loadPage } from "@opal/navigation";
import { launchOAuth, OAuthLaunchError } from "@/lib/oauth/launch";

// User OAuth Flow

// Mirrors `OAuthInitiateResponse` in backend/onyx/server/features/oauth_config/models.py.
interface OAuthInitiateResponse {
  authorization_url: string;
  state: string;
}

export async function getOAuthAuthorizationUrl(
  oauthConfigId: number,
  returnPath: string,
  invalidUrlMessage: string
): Promise<string> {
  const response = await fetch("/api/oauth-config/initiate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      oauth_config_id: oauthConfigId,
      return_path: returnPath,
    }),
  });

  if (!response.ok) {
    const errorData: ErrorResponseBody = await response
      .json()
      .catch(() => ({}));
    throw new Error(
      errorData.detail ||
        `Failed to initiate OAuth flow: ${response.statusText}`
    );
  }

  const data: OAuthInitiateResponse = await response.json();
  if (!/^https?:\/\//i.test(data.authorization_url)) {
    throw new Error(invalidUrlMessage);
  }

  return data.authorization_url;
}

export async function initiateOAuthFlow(
  oauthConfigId: number,
  returnPath: string,
  invalidUrlMessage: string
): Promise<void> {
  try {
    await launchOAuth(() =>
      getOAuthAuthorizationUrl(oauthConfigId, returnPath, invalidUrlMessage)
    );
  } catch (error) {
    if (
      !(error instanceof OAuthLaunchError) ||
      error.reason !== "popup_blocked"
    )
      throw error;
    loadPage(
      await getOAuthAuthorizationUrl(
        oauthConfigId,
        returnPath,
        invalidUrlMessage
      )
    );
  }
}
