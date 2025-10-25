import {
  OAuthConfig,
  OAuthConfigCreate,
  OAuthConfigUpdate,
  OAuthTokenStatus,
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

export async function getOAuthConfigs(): Promise<OAuthConfig[]> {
  const response = await fetch("/api/admin/oauth-config");

  if (!response.ok) {
    throw new Error(`Failed to fetch OAuth configs: ${response.statusText}`);
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

export async function deleteOAuthConfig(id: number): Promise<void> {
  const response = await fetch(`/api/admin/oauth-config/${id}`, {
    method: "DELETE",
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(
      errorData.detail ||
        `Failed to delete OAuth config: ${response.statusText}`
    );
  }
}

// User OAuth Flow

export async function initiateOAuthFlow(
  oauthConfigId: number,
  returnPath: string = "/chat"
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

export async function handleOAuthCallback(
  code: string,
  state: string,
  oauthConfigId: number
): Promise<{ success: boolean; redirect_url: string; error?: string }> {
  const response = await fetch("/api/oauth-config/callback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      code,
      state,
      oauth_config_id: oauthConfigId,
    }),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(
      errorData.detail || `OAuth callback failed: ${response.statusText}`
    );
  }

  return await response.json();
}

export async function getUserOAuthTokenStatus(): Promise<OAuthTokenStatus[]> {
  const response = await fetch("/api/user-oauth-token/status");

  if (!response.ok) {
    throw new Error(
      `Failed to fetch OAuth token status: ${response.statusText}`
    );
  }

  return await response.json();
}

export async function revokeOAuthToken(oauthConfigId: number): Promise<void> {
  const response = await fetch(`/api/oauth-config/${oauthConfigId}/token`, {
    method: "DELETE",
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(
      errorData.detail || `Failed to revoke OAuth token: ${response.statusText}`
    );
  }
}
