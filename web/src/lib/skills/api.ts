/**
 * Thin client wrappers around the skills API.
 *
 * Pairs with `backend/onyx/server/features/skill/api.py`. All mutations bubble
 * server-side `OnyxError` detail strings as Error messages so callers can hand
 * them to `toast.error` directly.
 */

import type {
  CustomSkill,
  GitHubSkillsImportResult,
  OrganizationLibraryDefaultAccess,
  OrganizationLibraryDefaultPolicy,
  GitHubSkillsPreview,
  Skill,
  SkillBundleContents,
  SkillEditableDetail,
  SkillSharePermission,
  SkillInstallationPolicy,
} from "@/lib/skills/types";

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let errorCode: string | undefined;
    let responseBody: unknown = null;
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      responseBody = body;
      if (typeof body?.error_code === "string") errorCode = body.error_code;
      if (typeof body?.detail === "string") detail = body.detail;
      else if (Array.isArray(body?.detail) && body.detail[0]?.msg) {
        detail = body.detail[0].msg;
      }
    } catch {
      // Use the generic status message.
    }
    const error = new Error(detail) as Error & {
      errorCode: string | undefined;
      responseBody: unknown;
    };
    error.errorCode = errorCode;
    error.responseBody = responseBody;
    throw error;
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return await res.json();
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

export async function previewGitHubSkills(
  repository: string
): Promise<GitHubSkillsPreview> {
  const res = await fetch("/api/skills/github/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repository }),
  });
  return handle<GitHubSkillsPreview>(res);
}

export async function importGitHubSkills(
  preview: Pick<GitHubSkillsPreview, "repository" | "revision" | "subpath">,
  paths: string[],
  sharing?: SkillShareUpdatePayload
): Promise<GitHubSkillsImportResult> {
  const res = await fetch("/api/skills/github/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      repository: preview.repository,
      revision: preview.revision,
      subpath: preview.subpath,
      paths,
      sharing,
    }),
  });
  return handle<GitHubSkillsImportResult>(res);
}

export async function uploadSkillBundles(
  bundles: File[],
  sharing?: SkillShareUpdatePayload
): Promise<GitHubSkillsImportResult> {
  const form = new FormData();
  for (const bundle of bundles) form.append("bundles", bundle);
  if (sharing) form.append("sharing", JSON.stringify(sharing));
  return handle<GitHubSkillsImportResult>(
    await fetch("/api/skills/custom/batch", { method: "POST", body: form })
  );
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
      const batch = await handle<BulkSkillResult>(
        await fetch("/api/skills/bulk", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...request, skill_ids }),
        })
      );
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

export interface CreateCustomSkillInput {
  name: string;
  description: string;
  instructions_markdown: string;
  auto_enable?: boolean;
  external_app_id?: number;
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
  if (input.external_app_id !== undefined) {
    form.append("external_app_id", String(input.external_app_id));
  }
  if (input.sharing) form.append("sharing", JSON.stringify(input.sharing));
  if (upload) form.append("upload", upload);

  const res = await fetch("/api/skills/custom/editor", {
    method: "POST",
    body: form,
  });
  return handle<SkillEditableDetail>(res);
}

export function isSkillNameConflict(error: unknown): boolean {
  return (
    error instanceof Error &&
    "errorCode" in error &&
    error.errorCode === "SKILL_NAME_CONFLICT"
  );
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
  const res = await fetch(`/api/skills/${skillId}/enabled`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled, replace_conflict: replaceConflict }),
  });
  return handle<Skill>(res);
}

export interface SkillGroupSettingPayload {
  group_id: number;
  /** Null: the group uses the organization setting. */
  installation_policy: SkillInstallationPolicy | null;
}

export interface SkillShareUpdatePayload {
  /** Null: no own setting, so Default Access applies. */
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
  const res = await fetch(`/api/skills/custom/${skillId}/files`, {
    method: "POST",
    body: form,
  });
  return handle<SkillEditableDetail>(res);
}

export async function inspectSkillBundle(
  upload: File
): Promise<SkillBundleContents> {
  const form = new FormData();
  form.append("upload", upload);
  const res = await fetch("/api/skills/custom/bundle/inspect", {
    method: "POST",
    body: form,
  });
  return handle<SkillBundleContents>(res);
}

export async function removeUserSkillFile(
  skillId: string,
  path: string,
  baseVersionId?: string | null
): Promise<SkillEditableDetail> {
  const params = new URLSearchParams({ path });
  if (baseVersionId) params.set("base_version_id", baseVersionId);
  const res = await fetch(
    `/api/skills/custom/${skillId}/files?${params.toString()}`,
    { method: "DELETE" }
  );
  return handle<SkillEditableDetail>(res);
}

export async function patchUserSkill(
  skillId: string,
  patch: PatchCustomSkillInput
): Promise<CustomSkill> {
  const res = await fetch(`/api/skills/custom/${skillId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return handle<CustomSkill>(res);
}

export async function updateSkillShares(
  skillId: string,
  payload: SkillShareUpdatePayload
): Promise<CustomSkill> {
  const res = await fetch(`/api/skills/custom/${skillId}/share`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return handle<CustomSkill>(res);
}

export async function transferSkillOwnership(
  skillId: string,
  payload: { new_owner_user_id: string }
): Promise<CustomSkill> {
  const res = await fetch(`/api/skills/custom/${skillId}/transfer-ownership`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return handle<CustomSkill>(res);
}

export async function restoreSkillVersion(
  skillId: string,
  versionId: string,
  baseVersionId: string
): Promise<SkillEditableDetail> {
  const res = await fetch(
    `/api/skills/custom/${skillId}/versions/${versionId}/restore`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ base_version_id: baseVersionId }),
    }
  );
  return handle<SkillEditableDetail>(res);
}

/** Publish the current version: a first publish, or a publish update. Under
 * the Publishing setting this can make a review request instead. */
export async function publishSkill(
  skillId: string,
  baseVersionId: string
): Promise<CustomSkill> {
  const res = await fetch(`/api/skills/custom/${skillId}/publish`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ base_version_id: baseVersionId }),
  });
  return handle<CustomSkill>(res);
}

export async function reviewSkillVersion(
  skillId: string,
  versionId: string,
  decision: "approve" | "deny"
): Promise<CustomSkill> {
  const res = await fetch(
    `/api/skills/custom/${skillId}/versions/${versionId}/${decision}`,
    { method: "POST" }
  );
  return handle<CustomSkill>(res);
}

export async function deleteUserSkill(skillId: string): Promise<void> {
  const res = await fetch(`/api/skills/custom/${skillId}`, {
    method: "DELETE",
  });
  await handle<void>(res);
}

/** Set the install setting of every published skill with no own setting. */
export async function setOrganizationLibraryDefaultAccess(
  policy: OrganizationLibraryDefaultPolicy
): Promise<OrganizationLibraryDefaultAccess> {
  const res = await fetch("/api/skills/organization-library/default-access", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ installation_policy: policy }),
  });
  return handle<OrganizationLibraryDefaultAccess>(res);
}
