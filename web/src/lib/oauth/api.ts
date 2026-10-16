import type { ErrorResponseBody } from "@/lib/fetcher";
import {
  OAuthConfig,
  OAuthConfigCreate,
  OAuthConfigUpdate,
} from "@/lib/tools/types";

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
    const errorData: ErrorResponseBody = await response
      .json()
      .catch(() => ({}));
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
    const errorData: ErrorResponseBody = await response
      .json()
      .catch(() => ({}));
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
    const errorData: ErrorResponseBody = await response
      .json()
      .catch(() => ({}));
    throw new Error(
      errorData.detail ||
        `Failed to update OAuth config: ${response.statusText}`
    );
  }

  return await response.json();
}

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
  window.location.href = await getOAuthAuthorizationUrl(
    oauthConfigId,
    returnPath,
    invalidUrlMessage
  );
}

export interface OAuthTestRequest {
  oauth_config_id?: number;
  authorization_url: string;
  token_url: string;
  client_id?: string;
  client_secret?: string;
  scopes: string[];
  supports_pkce: boolean;
}

export type PKCESupportStatus = "supported" | "unsupported" | "unknown";

export async function discoverPKCESupport(
  authorizationUrl: string,
  tokenUrl: string
): Promise<PKCESupportStatus> {
  const response = await fetch("/api/admin/oauth-config/pkce-support", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      authorization_url: authorizationUrl,
      token_url: tokenUrl,
    }),
  });
  if (!response.ok) throw new Error("PKCE discovery failed");
  const data: unknown = await response.json();
  if (
    data &&
    typeof data === "object" &&
    "status" in data &&
    (data.status === "supported" ||
      data.status === "unsupported" ||
      data.status === "unknown")
  ) {
    return data.status;
  }
  throw new Error("Invalid PKCE discovery response");
}

export async function initiateOAuthTest(
  request: OAuthTestRequest,
  signal: AbortSignal
): Promise<OAuthInitiateResponse> {
  const response = await fetch("/api/admin/oauth-config/test/initiate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal,
  });
  if (!response.ok) throw new Error("OAuth test initiation failed");
  const data: unknown = await response.json();
  if (
    !data ||
    typeof data !== "object" ||
    !("state" in data) ||
    typeof data.state !== "string" ||
    !data.state ||
    !("authorization_url" in data) ||
    typeof data.authorization_url !== "string" ||
    new URL(data.authorization_url).protocol !== "https:"
  ) {
    throw new Error("Invalid OAuth test response");
  }
  return { state: data.state, authorization_url: data.authorization_url };
}

export async function completeOAuthTest(
  code: string,
  state: string
): Promise<boolean> {
  const query = new URLSearchParams({ code, state });
  const response = await fetch(
    `/api/admin/oauth-config/test/callback?${query}`,
    {
      method: "POST",
      credentials: "include",
    }
  );
  if (!response.ok) throw new Error("OAuth connection test failed");
  const data: unknown = await response.json();
  if (
    !data ||
    typeof data !== "object" ||
    !("supports_pkce" in data) ||
    typeof data.supports_pkce !== "boolean"
  ) {
    throw new Error("Invalid OAuth test callback response");
  }
  return data.supports_pkce;
}
