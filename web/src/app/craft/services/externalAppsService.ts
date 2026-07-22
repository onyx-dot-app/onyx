/**
 * HTTP service for External Apps endpoints. UI components import from
 * here instead of calling `fetch` directly, so error shape + URL
 * construction live in one place.
 */

import {
  EndpointPolicy,
  ExternalAppAdminResponse,
  ExternalAppType,
} from "@/app/craft/v1/apps/registry";
import { BUILD_API_BASE } from "@/app/craft/v1/constants";

async function readErrorDetail(
  res: Response,
  fallback: string
): Promise<string> {
  const data = (await res.json().catch(() => ({}))) as { detail?: string };
  return data.detail ?? `${fallback} (HTTP ${res.status}).`;
}

interface CreateBuiltInExternalAppBody {
  name: string;
  app_type: ExternalAppType;
  upstream_url_patterns: string[];
  auth_template: Record<string, string>;
  organization_credentials: Record<string, string>;
  // Full replace when present; omit to default every action to ASK.
  action_policies?: Record<string, EndpointPolicy>;
}

/**
 * Create a built-in external app (`POST /admin/apps/built-in`). Built-in
 * providers only — custom apps use {@link createCustomExternalApp}. Updates go
 * through {@link updateExternalApp}.
 */
export async function createBuiltInExternalApp(
  body: CreateBuiltInExternalAppBody
): Promise<ExternalAppAdminResponse> {
  const res = await fetch(`${BUILD_API_BASE}/admin/apps/built-in`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "Save failed"));
  }
  return res.json();
}

interface CreateCustomExternalAppInput {
  name: string;
  upstream_url_patterns: string[];
  auth_template: Record<string, string>;
  organization_credentials: Record<string, string>;
}

/**
 * Create a CUSTOM external app (`POST /admin/apps/custom`). Skill content is
 * created and managed independently through the Skills experience.
 */
export async function createCustomExternalApp(
  input: CreateCustomExternalAppInput
): Promise<ExternalAppAdminResponse> {
  const res = await fetch(`${BUILD_API_BASE}/admin/apps/custom`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "Save failed"));
  }
  return res.json();
}

interface UpdateExternalAppBody {
  // Every field is optional; omit to leave the stored value untouched.
  enabled?: boolean;
  name?: string;
  upstream_url_patterns?: string[];
  auth_template?: Record<string, string>;
  organization_credentials?: Record<string, string>;
  // Full replace when present; omit to leave stored policies untouched.
  action_policies?: Record<string, EndpointPolicy>;
}

/**
 * Partial update of any app (PATCH /admin/apps/{id}). For Onyx-managed built-ins
 * the gateway-config fields are ignored server-side (only policies
 * apply).
 */
export async function updateExternalApp(
  id: number,
  body: UpdateExternalAppBody
): Promise<ExternalAppAdminResponse> {
  const res = await fetch(`${BUILD_API_BASE}/admin/apps/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "Save failed"));
  }
  return res.json();
}

export async function deleteExternalApp(id: number): Promise<void> {
  const res = await fetch(`${BUILD_API_BASE}/admin/apps/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "Delete failed"));
  }
}

interface OAuthStartResponse {
  authorize_url: string;
}

export async function startExternalAppOAuth(
  externalAppId: number
): Promise<OAuthStartResponse> {
  const res = await fetch(
    `${BUILD_API_BASE}/apps/${externalAppId}/oauth/start`
  );
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "Failed to start OAuth"));
  }
  return res.json();
}

interface OAuthCallbackResponse {
  success: boolean;
  external_app_id: number;
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

/** "Disconnect" by clearing stored user credentials. */
export async function disconnectUserFromApp(
  externalAppId: number
): Promise<void> {
  return upsertUserCredentials(externalAppId, {});
}
