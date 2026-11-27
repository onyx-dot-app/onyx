/**
 * Thin client wrappers around the skills API.
 *
 * Pairs with `backend/onyx/server/features/skill/api.py`. All mutations bubble
 * server-side `OnyxError` detail strings as Error messages so callers can hand
 * them to `toast.error` directly.
 */

import { FetchError, type ErrorResponseBody } from "@/lib/fetcher";
import type {
  PluginUploadPreview,
  PluginUploadTarget,
} from "@/lib/plugins/types";
import type {
  CustomSkill,
  GitHubSkillsImportResult,
  OrganizationLibraryDefaultAccess,
  OrganizationLibraryDefaultPolicy,
  Skill,
  SkillBundleContents,
  SkillEditableDetail,
  SkillSharePermission,
  SkillInstallationPolicy,
} from "@/lib/skills/types";

async function skillsFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let errorCode: string | undefined;
    let info: ErrorResponseBody | null = null;
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      info = body;
      if (typeof body?.error_code === "string") errorCode = body.error_code;
      if (typeof body?.detail === "string") detail = body.detail;
      else if (Array.isArray(body?.detail) && body.detail[0]?.msg) {
        detail = body.detail[0].msg;
      }
    } catch {
      // Use the generic status message.
    }
    throw Object.assign(new FetchError(detail, res.status, info), {
      errorCode,
    });
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return await res.json();
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

export async function uploadSkillBundles(
  bundles: File[],
  sharing?: SkillShareUpdatePayload
): Promise<GitHubSkillsImportResult> {
  const form = new FormData();
  for (const bundle of bundles) form.append("bundles", bundle);
  if (sharing) form.append("sharing", JSON.stringify(sharing));
  return skillsFetch<GitHubSkillsImportResult>("/api/skills/custom/batch", {
    method: "POST",
    body: form,
  });
}

export type BulkSkillRequest = {
  skill_ids: string[];
} & (
  | { action: "share"; sharing: SkillShareUpdatePayload }
  | { action: "enable" | "disable" | "delete" }
);

export interface BulkSkillResult {
  succeeded: string[];
  failed: { skill_id: string; detail: string }[];
}

export async function bulkUpdateSkills(
  request: BulkSkillRequest
): Promise<BulkSkillResult> {
  const result: BulkSkillResult = { succeeded: [], failed: [] };
  const batchSize = 500;
  for (let offset = 0; offset < request.skill_ids.length; offset += batchSize) {
    const skill_ids = request.skill_ids.slice(offset, offset + batchSize);
    try {
      const batch = await skillsFetch<BulkSkillResult>("/api/skills/bulk", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...request, skill_ids }),
      });
      result.succeeded.push(...batch.succeeded);
      result.failed.push(...batch.failed);
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      result.failed.push(
        ...skill_ids.map((skill_id) => ({ skill_id, detail }))
      );
    }
  }
  return result;
}

/** `pluginId` binds the upload to that plugin: it adds a version to it. */
function pluginUploadForm(
  bundle: File,
  saveAsNew: boolean,
  pluginId?: string
): FormData {
  const form = new FormData();
  form.append("bundle", bundle);
  form.append("save_as_new", String(saveAsNew));
  if (pluginId) form.append("plugin_id", pluginId);
  return form;
}

export async function inspectPluginUpload(
  bundle: File,
  saveAsNew: boolean,
  pluginId?: string
): Promise<PluginUploadPreview> {
  return skillsFetch<PluginUploadPreview>("/api/skills/plugins/inspect", {
    method: "POST",
    body: pluginUploadForm(bundle, saveAsNew, pluginId),
  });
}

export interface PluginUploadResult {
  target: PluginUploadTarget;
  plugin: CustomSkill;
  enabled: boolean;
  unchanged: boolean;
  name_conflicts: string[];
}

export async function savePluginUpload(
  bundle: File,
  saveAsNew: boolean,
  pluginId?: string
): Promise<PluginUploadResult> {
  return skillsFetch<PluginUploadResult>("/api/skills/plugins", {
    method: "POST",
    body: pluginUploadForm(bundle, saveAsNew, pluginId),
  });
}

export interface CreateCustomSkillInput {
  name: string;
  description: string;
  instructions_markdown: string;
  auto_enable?: boolean;
  sharing?: SkillShareUpdatePayload;
}

export async function createCustomSkillFromEditor(
  input: CreateCustomSkillInput,
  upload?: File
): Promise<SkillEditableDetail> {
  const form = new FormData();
  form.append("name", input.name);
  form.append("description", input.description);
  form.append("instructions_markdown", input.instructions_markdown);
  form.append("auto_enable", String(input.auto_enable ?? true));
  if (input.sharing) form.append("sharing", JSON.stringify(input.sharing));
  if (upload) form.append("upload", upload);

  return skillsFetch<SkillEditableDetail>("/api/skills/custom/editor", {
    method: "POST",
    body: form,
  });
}

export function isSkillNameConflict(error: unknown): boolean {
  return (
    error instanceof Error &&
    "errorCode" in error &&
    error.errorCode === "SKILL_NAME_CONFLICT"
  );
}

/** The skills that a turn-on would turn off, from a name-conflict error. */
export function skillNameConflictNames(error: unknown): string[] {
  if (!(error instanceof FetchError)) return [];
  const names: unknown =
    error.info && "conflict_names" in error.info
      ? error.info.conflict_names
      : undefined;
  return Array.isArray(names)
    ? names.filter((name): name is string => typeof name === "string")
    : [];
}

export function isSkillVersionStale(error: unknown): boolean {
  return (
    error instanceof Error &&
    "errorCode" in error &&
    error.errorCode === "PLUGIN_VERSION_STALE"
  );
}

export interface PatchCustomSkillInput {
  description?: string;
  instructions_markdown?: string;
  public_permission?: SkillSharePermission | null;
  /** The version the edit starts from. A newer saved version gives a 409. */
  base_version_id?: string | null;
}

export async function setSkillEnabled(
  skillId: string,
  enabled: boolean,
  replaceConflict = false
): Promise<Skill> {
  return skillsFetch<Skill>(`/api/skills/${skillId}/enabled`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled, replace_conflict: replaceConflict }),
  });
}

export interface SkillGroupSettingPayload {
  group_id: number;
  /** Null: the group uses the organization setting. */
  installation_policy: SkillInstallationPolicy | null;
}

export interface SkillShareUpdatePayload {
  /** Null: no own setting, so Default access applies. */
  installation_policy?: SkillInstallationPolicy | null;
  user_shares?: {
    user_id: string;
    permission: SkillSharePermission;
  }[];
  group_shares?: {
    group_id: number;
    permission: SkillSharePermission;
  }[];
  public_permission?: SkillSharePermission | null;
  group_settings?: SkillGroupSettingPayload[];
}

export async function uploadUserSkillFiles(
  skillId: string,
  upload: File,
  baseVersionId?: string | null
): Promise<SkillEditableDetail> {
  const form = new FormData();
  form.append("upload", upload);
  if (baseVersionId) form.append("base_version_id", baseVersionId);
  return skillsFetch<SkillEditableDetail>(
    `/api/skills/custom/${skillId}/files`,
    {
      method: "POST",
      body: form,
    }
  );
}

export async function inspectSkillBundle(
  upload: File
): Promise<SkillBundleContents> {
  const form = new FormData();
  form.append("upload", upload);
  return skillsFetch<SkillBundleContents>("/api/skills/custom/bundle/inspect", {
    method: "POST",
    body: form,
  });
}

export async function removeUserSkillFile(
  skillId: string,
  path: string,
  baseVersionId?: string | null
): Promise<SkillEditableDetail> {
  const params = new URLSearchParams({ path });
  if (baseVersionId) params.set("base_version_id", baseVersionId);
  return skillsFetch<SkillEditableDetail>(
    `/api/skills/custom/${skillId}/files?${params.toString()}`,
    { method: "DELETE" }
  );
}

export async function patchUserSkill(
  skillId: string,
  patch: PatchCustomSkillInput
): Promise<CustomSkill> {
  return skillsFetch<CustomSkill>(`/api/skills/custom/${skillId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export async function updateSkillShares(
  skillId: string,
  payload: SkillShareUpdatePayload
): Promise<CustomSkill> {
  return skillsFetch<CustomSkill>(`/api/skills/custom/${skillId}/share`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function transferSkillOwnership(
  skillId: string,
  payload: { new_owner_user_id: string }
): Promise<CustomSkill> {
  return skillsFetch<CustomSkill>(
    `/api/skills/custom/${skillId}/transfer-ownership`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export async function restoreSkillVersion(
  skillId: string,
  versionId: string,
  baseVersionId: string
): Promise<SkillEditableDetail> {
  return skillsFetch<SkillEditableDetail>(
    `/api/skills/custom/${skillId}/versions/${versionId}/restore`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ base_version_id: baseVersionId }),
    }
  );
}

/** Publish the current version: a first publish, or a publish update. Under
 * the Publishing setting this can make a review request instead. */
export async function publishSkill(
  skillId: string,
  baseVersionId: string
): Promise<CustomSkill> {
  return skillsFetch<CustomSkill>(`/api/skills/custom/${skillId}/publish`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ base_version_id: baseVersionId }),
  });
}

export async function reviewSkillVersion(
  skillId: string,
  versionId: string,
  decision: "approve" | "deny"
): Promise<CustomSkill> {
  return skillsFetch<CustomSkill>(
    `/api/skills/custom/${skillId}/versions/${versionId}/${decision}`,
    { method: "POST" }
  );
}

export async function deleteUserSkill(skillId: string): Promise<void> {
  await skillsFetch<void>(`/api/skills/custom/${skillId}`, {
    method: "DELETE",
  });
}

/** Set the install setting of every published skill with no own setting. */
export async function setOrganizationLibraryDefaultAccess(
  policy: OrganizationLibraryDefaultPolicy
): Promise<OrganizationLibraryDefaultAccess> {
  return skillsFetch<OrganizationLibraryDefaultAccess>(
    "/api/skills/organization-library/default-access",
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ installation_policy: policy }),
    }
  );
}
