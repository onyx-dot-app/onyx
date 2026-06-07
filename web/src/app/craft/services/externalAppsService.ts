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
  description: string;
  app_type: ExternalAppType;
  upstream_url_patterns: string[];
  auth_template: Record<string, string>;
  organization_credentials: Record<string, string>;
  enabled: boolean;
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
  description: string;
  upstream_url_patterns: string[];
  auth_template: Record<string, string>;
  organization_credentials: Record<string, string>;
  enabled: boolean;
  /** Required — the skill bundle whose filename becomes the app slug. */
  bundle: File;
}

/**
 * Create a CUSTOM external app (`POST /admin/apps/custom`). Multipart so the
 * bundle can be uploaded; structured fields are JSON-encoded form strings.
 * Field edits go through {@link updateExternalApp}; bundle replacement through
 * {@link replaceCustomAppBundle}.
 */
export async function createCustomExternalApp(
  input: CreateCustomExternalAppInput
): Promise<ExternalAppAdminResponse> {
  const form = new FormData();
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
  form.append("bundle", input.bundle);

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
 * Replace a custom app's bundle bytes, keeping its slug
 * (`PUT /admin/apps/{id}/bundle`). The only multipart channel for edits; all
 * other field edits go through {@link updateExternalApp}.
 */
export async function replaceCustomAppBundle(
  id: number,
  bundle: File
): Promise<ExternalAppAdminResponse> {
  const form = new FormData();
  form.append("bundle", bundle);

  const res = await fetch(`${BUILD_API_BASE}/admin/apps/${id}/bundle`, {
    method: "PUT",
    body: form,
  });
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "Bundle replace failed"));
  }
  return res.json();
}

interface UpdateExternalAppBody {
  // Every field is optional; omit to leave the stored value untouched.
  enabled?: boolean;
  name?: string;
  description?: string;
  upstream_url_patterns?: string[];
  auth_template?: Record<string, string>;
  organization_credentials?: Record<string, string>;
  // Full replace when present; omit to leave stored policies untouched.
  action_policies?: Record<string, EndpointPolicy>;
}

/**
 * Partial update of any app (PATCH /admin/apps/{id}). For Onyx-managed built-ins
 * the gateway-config fields are ignored server-side (only enablement + policies
 * apply); a custom app's bundle bytes go through {@link replaceCustomAppBundle}.
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

/**
 * Toggle `enabled` without touching credentials or stored policies — works the
 * same for built-in and custom apps via the PATCH endpoint.
 */
export async function setExternalAppEnabled(
  app: ExternalAppAdminResponse,
  enabled: boolean
): Promise<ExternalAppAdminResponse> {
  return updateExternalApp(app.id, { enabled });
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
