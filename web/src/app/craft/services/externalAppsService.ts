/**
 * HTTP service for External Apps endpoints. UI components import from
 * here instead of calling `fetch` directly, so error shape + URL
 * construction live in one place.
 */

import { ActionPolicy, ExternalAppType } from "@/app/craft/v1/apps/registry";
import { BUILD_API_BASE } from "@/app/craft/v1/constants";
import type { ErrorResponseBody } from "@/lib/fetcher";

async function readErrorDetail(
  res: Response,
  fallback: string
): Promise<string> {
  const data: ErrorResponseBody = await res.json().catch(() => ({}));
  return data.detail ?? `${fallback} (HTTP ${res.status}).`;
}

interface CreateBuiltInExternalAppBody {
  enabled?: boolean;
  users_can_manage_policies?: boolean;
  name: string;
  app_type: ExternalAppType;
  upstream_url_patterns: string[];
  auth_template: Record<string, string>;
  organization_credentials: Record<string, string>;
  // Full replace when present; omit to default every action to ASK.
  action_policies?: Record<string, ActionPolicy>;
}

interface CreateCustomExternalAppInput {
  enabled?: boolean;
  users_can_manage_policies?: boolean;
  name: string;
  upstream_url_patterns: string[];
  auth_template: Record<string, string>;
  organization_credentials: Record<string, string>;
}

interface UpdateExternalAppBody {
  users_can_manage_policies?: boolean;
  // Every field is optional; omit to leave the stored value untouched.
  enabled?: boolean;
  name?: string;
  upstream_url_patterns?: string[];
  auth_template?: Record<string, string>;
  organization_credentials?: Record<string, string>;
  // Full replace when present; omit to leave stored policies untouched.
  action_policies?: Record<string, ActionPolicy>;
}

interface OAuthStartResponse {
  authorize_url: string;
}

export async function startExternalAppOAuth(
  externalAppId: number,
  returnPath?: string
): Promise<OAuthStartResponse> {
  const res = await fetch(
    `${BUILD_API_BASE}/apps/${externalAppId}/oauth/start${returnPath ? `?${new URLSearchParams({ return_path: returnPath })}` : ""}`
  );
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "Failed to start OAuth"));
  }
  return res.json();
}

interface OAuthCallbackResponse {
  success: boolean;
  external_app_id: number;
  return_path?: string | null;
}

export async function completeExternalAppOAuthCallback(
  code: string,
  state: string
): Promise<OAuthCallbackResponse> {
  const res = await fetch(`${BUILD_API_BASE}/apps/oauth/callback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, state }),
  });
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "OAuth exchange failed"));
  }
  return res.json();
}

export type ConnectAppDecision = "connected" | "declined";

/**
 * Resolve a parked `connect_app` request. The api-server is blocking the
 * agent's tool call on this decision: "connected" allows it, "declined" hands
 * the agent a rejection result so it can choose an alternative.
 */
export async function postConnectAppDecision(
  requestId: string,
  decision: ConnectAppDecision
): Promise<void> {
  const res = await fetch(
    `${BUILD_API_BASE}/apps/connect/${requestId}/decision`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision }),
    }
  );
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "Failed to resolve connection"));
  }
}

export async function upsertUserCredentials(
  externalAppId: number,
  userCredentials: Record<string, unknown>
): Promise<void> {
  const res = await fetch(
    `${BUILD_API_BASE}/apps/${externalAppId}/credentials`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_credentials: userCredentials }),
    }
  );
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "Failed to save credentials"));
  }
}

export async function disconnectUserFromApp(
  externalAppId: number
): Promise<void> {
  const res = await fetch(
    `${BUILD_API_BASE}/apps/${externalAppId}/credentials`,
    { method: "DELETE" }
  );
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "Failed to disconnect app"));
  }
}
