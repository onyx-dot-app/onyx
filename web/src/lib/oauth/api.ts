import {
  OAuthConfig,
  OAuthConfigCreate,
  OAuthConfigUpdate,
} from "@/lib/tools/interfaces";

// Admin OAuth Config Management

export async function createOAuthConfig(
  config: OAuthConfigCreate
): Promise<OAuthConfig> {
  const response = await fetch("/api/admin/oauth-config/create", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(
      errorData.detail ||
        `Failed to create OAuth config: ${response.statusText}`
    );
  }

  return await response.json();
}

export async function getOAuthConfig(id: number): Promise<OAuthConfig> {
  const response = await fetch(`/api/admin/oauth-config/${id}`);

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(
      errorData.detail || `Failed to fetch OAuth config: ${response.statusText}`
    );
  }

  return await response.json();
}

export async function updateOAuthConfig(
  id: number,
  updates: OAuthConfigUpdate
): Promise<OAuthConfig> {
  const response = await fetch(`/api/admin/oauth-config/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(
      errorData.detail ||
        `Failed to update OAuth config: ${response.statusText}`
    );
  }

  return await response.json();
}

// User OAuth Flow

export async function initiateOAuthFlow(
  oauthConfigId: number,
  returnPath: string = "/app"
): Promise<void> {
  const response = await fetch("/api/oauth-config/initiate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      oauth_config_id: oauthConfigId,
      return_path: returnPath,
    }),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(
      errorData.detail ||
        `Failed to initiate OAuth flow: ${response.statusText}`
    );
  }

  const data = await response.json();
  // Redirect to authorization URL
  window.location.href = data.authorization_url;
}
