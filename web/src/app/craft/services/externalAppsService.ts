/**
 * HTTP service for External Apps endpoints. UI components import from
 * here instead of calling `fetch` directly, so error shape + URL
 * construction live in one place.
 */

import {
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

interface UpsertExternalAppBody {
  id: number | null;
  name: string;
  description: string;
  app_type: ExternalAppType;
  upstream_url_patterns: string[];
  auth_template: Record<string, string>;
  organization_credentials: Record<string, string>;
  enabled: boolean;
}

export async function upsertExternalApp(
  body: UpsertExternalAppBody
): Promise<ExternalAppAdminResponse> {
  const res = await fetch(`${BUILD_API_BASE}/admin/apps`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "Save failed"));
  }
  return res.json();
}

/** Toggle `enabled` without touching credentials. */
export async function setExternalAppEnabled(
  app: ExternalAppAdminResponse,
  enabled: boolean
): Promise<ExternalAppAdminResponse> {
  return upsertExternalApp({
    id: app.id,
    name: app.name,
    description: app.description,
    app_type: app.app_type,
    upstream_url_patterns: app.upstream_url_patterns,
    auth_template: app.auth_template,
    organization_credentials: app.organization_credentials,
    enabled,
  });
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

export async function completeExternalAppOAuthCallback(
  code: string,
  state: string
): Promise<void> {
  const res = await fetch(`${BUILD_API_BASE}/apps/oauth/callback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, state }),
  });
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "OAuth exchange failed"));
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
