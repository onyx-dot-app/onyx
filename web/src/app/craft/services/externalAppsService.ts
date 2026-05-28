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

interface UpsertExternalAppBody {
  id: number | null;
  name: string;
  description: string;
  app_type: ExternalAppType;
  upstream_url_patterns: string[];
  auth_template: Record<string, string>;
  organization_credentials: Record<string, string>;
  enabled: boolean;
  // Full replace when present; omit to leave stored policies untouched.
  action_policies?: Record<string, EndpointPolicy>;
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

interface UpsertCustomExternalAppInput {
  /** Omit to create; set to edit an existing custom app. */
  id?: number;
  name: string;
  description: string;
  upstream_url_patterns: string[];
  auth_template: Record<string, string>;
  organization_credentials: Record<string, string>;
  enabled: boolean;
  /** Required on create; optional on edit (when set, replaces the bundle). */
  bundle?: File;
}

/**
 * Create or edit a CUSTOM external app. Custom apps go through this multipart
 * endpoint (never the JSON `/admin/apps`) so their bundle can be uploaded or
 * replaced. The structured fields are JSON-encoded form strings to match the
 * backend's `POST /admin/apps/custom` handler.
 */
export async function upsertCustomExternalApp(
  input: UpsertCustomExternalAppInput
): Promise<ExternalAppAdminResponse> {
  const form = new FormData();
  if (input.id !== undefined) form.append("app_id", String(input.id));
  form.append("name", input.name);
  form.append("description", input.description);
  form.append("enabled", String(input.enabled));
  form.append(
    "upstream_url_patterns",
    JSON.stringify(input.upstream_url_patterns)
  );
  form.append("auth_template", JSON.stringify(input.auth_template));
  form.append(
    "organization_credentials",
    JSON.stringify(input.organization_credentials)
  );
  if (input.bundle) form.append("bundle", input.bundle);

  // No explicit Content-Type — the browser sets the multipart boundary.
  const res = await fetch(`${BUILD_API_BASE}/admin/apps/custom`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "Save failed"));
  }
  return res.json();
}

/**
 * Toggle `enabled` without touching credentials. Custom apps route through the
 * custom endpoint (resending their current config, no bundle); built-in
 * providers use the JSON endpoint.
 */
export async function setExternalAppEnabled(
  app: ExternalAppAdminResponse,
  enabled: boolean
): Promise<ExternalAppAdminResponse> {
  if (app.app_type === "CUSTOM") {
    return upsertCustomExternalApp({
      id: app.id,
      name: app.name,
      description: app.description,
      upstream_url_patterns: app.upstream_url_patterns,
      auth_template: app.auth_template,
      organization_credentials: app.organization_credentials,
      enabled,
    });
  }
  return upsertExternalApp({
    id: app.id,
    name: app.name,
    description: app.description,
    app_type: app.app_type,
    upstream_url_patterns: app.upstream_url_patterns,
    auth_template: app.auth_template,
    organization_credentials: app.organization_credentials,
    enabled,
    // action_policies omitted: a toggle must not touch stored policies.
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
