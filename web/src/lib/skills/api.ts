/**
 * Thin client wrappers around the skills API.
 *
 * Pairs with `backend/onyx/server/features/skill/api.py`. All mutations bubble
 * server-side `OnyxError` detail strings as Error messages so callers can hand
 * them to `toast.error` directly.
 */

import { errorHandlingFetchWith, FetchError } from "@/lib/fetcher";
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
import { SWR_KEYS } from "@/lib/swr-keys";

type HttpMethod = "POST" | "PUT" | "PATCH" | "DELETE";

interface SkillEnabledRequest {
  enabled: boolean;
  replace_conflict: boolean;
}

interface SkillOwnershipTransfer {
  new_owner_user_id: string;
}

interface SkillBaseVersionRequest {
  base_version_id: string;
}

interface OrganizationLibraryDefaultAccessRequest {
  installation_policy: OrganizationLibraryDefaultPolicy;
}

type SkillRequestBody =
  | FormData
  | BulkSkillRequest
  | SkillEnabledRequest
  | PatchCustomSkillInput
  | SkillShareUpdatePayload
  | SkillOwnershipTransfer
  | SkillBaseVersionRequest
  | OrganizationLibraryDefaultAccessRequest;

function send<T>(
  url: string,
  method: HttpMethod,
  body?: SkillRequestBody
): Promise<T> {
  if (body === undefined) return errorHandlingFetchWith<T>(url, { method });
  if (body instanceof FormData) {
    return errorHandlingFetchWith<T>(url, { method, body });
  }
  return errorHandlingFetchWith<T>(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function customSkillUrl(skillId: string): string {
  return `${SWR_KEYS.userSkills}/custom/${skillId}`;
}

function hasErrorCode(error: unknown, errorCode: string): boolean {
  return error instanceof FetchError && error.info?.error_code === errorCode;
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
  return send(`${SWR_KEYS.userSkills}/custom/batch`, "POST", form);
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
      const batch = await send<BulkSkillResult>(
        `${SWR_KEYS.userSkills}/bulk`,
        "POST",
        { ...request, skill_ids }
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

function pluginUploadForm(bundle: File, saveAsNew: boolean): FormData {
  const form = new FormData();
  form.append("bundle", bundle);
  form.append("save_as_new", String(saveAsNew));
  return form;
}

export async function inspectPluginUpload(
  bundle: File,
  saveAsNew: boolean
): Promise<PluginUploadPreview> {
  return send(
    `${SWR_KEYS.userSkills}/plugins/inspect`,
    "POST",
    pluginUploadForm(bundle, saveAsNew)
  );
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
  saveAsNew: boolean
): Promise<PluginUploadResult> {
  return send(
    `${SWR_KEYS.userSkills}/plugins`,
    "POST",
    pluginUploadForm(bundle, saveAsNew)
  );
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

  return send(`${SWR_KEYS.userSkills}/custom/editor`, "POST", form);
}

export function isSkillNameConflict(error: unknown): boolean {
  return hasErrorCode(error, "SKILL_NAME_CONFLICT");
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
  return hasErrorCode(error, "PLUGIN_VERSION_STALE");
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
  return send(`${SWR_KEYS.userSkill(skillId)}/enabled`, "PUT", {
    enabled,
    replace_conflict: replaceConflict,
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
  return send(`${customSkillUrl(skillId)}/files`, "POST", form);
}

export async function inspectSkillBundle(
  upload: File
): Promise<SkillBundleContents> {
  const form = new FormData();
  form.append("upload", upload);
  return send(`${SWR_KEYS.userSkills}/custom/bundle/inspect`, "POST", form);
}

export async function removeUserSkillFile(
  skillId: string,
  path: string,
  baseVersionId?: string | null
): Promise<SkillEditableDetail> {
  const params = new URLSearchParams({ path });
  if (baseVersionId) params.set("base_version_id", baseVersionId);
  return send(
    `${customSkillUrl(skillId)}/files?${params.toString()}`,
    "DELETE"
  );
}

export async function patchUserSkill(
  skillId: string,
  patch: PatchCustomSkillInput
): Promise<CustomSkill> {
  return send(customSkillUrl(skillId), "PATCH", patch);
}

export async function updateSkillShares(
  skillId: string,
  payload: SkillShareUpdatePayload
): Promise<CustomSkill> {
  return send(SWR_KEYS.skillSharing(skillId), "PATCH", payload);
}

export async function transferSkillOwnership(
  skillId: string,
  payload: SkillOwnershipTransfer
): Promise<CustomSkill> {
  return send(`${customSkillUrl(skillId)}/transfer-ownership`, "POST", payload);
}

export async function restoreSkillVersion(
  skillId: string,
  versionId: string,
  baseVersionId: string
): Promise<SkillEditableDetail> {
  return send(`${SWR_KEYS.skillVersion(skillId, versionId)}/restore`, "POST", {
    base_version_id: baseVersionId,
  });
}

/** Publish the current version: a first publish, or a publish update. Under
 * the Publishing setting this can make a review request instead. */
export async function publishSkill(
  skillId: string,
  baseVersionId: string
): Promise<CustomSkill> {
  return send(`${customSkillUrl(skillId)}/publish`, "POST", {
    base_version_id: baseVersionId,
  });
}

export async function reviewSkillVersion(
  skillId: string,
  versionId: string,
  decision: "approve" | "deny"
): Promise<CustomSkill> {
  return send(
    `${SWR_KEYS.skillVersion(skillId, versionId)}/${decision}`,
    "POST"
  );
}

export async function deleteUserSkill(skillId: string): Promise<void> {
  await send<null>(customSkillUrl(skillId), "DELETE");
}

/** Set the install setting of every published skill with no own setting. */
export async function setOrganizationLibraryDefaultAccess(
  policy: OrganizationLibraryDefaultPolicy
): Promise<OrganizationLibraryDefaultAccess> {
  return send(SWR_KEYS.organizationLibraryDefaultAccess, "PUT", {
    installation_policy: policy,
  });
}
