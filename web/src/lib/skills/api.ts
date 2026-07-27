/**
 * Thin client wrappers around the skills API.
 *
 * Pairs with `backend/onyx/server/features/skill/api.py`. All mutations bubble
 * server-side `OnyxError` detail strings as Error messages so callers can hand
 * them to `toast.error` directly.
 */

import type {
  CustomSkill,
  Skill,
  SkillBundleContents,
  SkillEditableDetail,
  SkillSharePermission,
} from "@/lib/skills/types";

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let errorCode: string | undefined;
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
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
    };
    error.errorCode = errorCode;
    throw error;
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

export interface CreateCustomSkillInput {
  name: string;
  description: string;
  instructions_markdown: string;
  auto_enable?: boolean;
  external_app_id?: number;
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

export interface PatchCustomSkillInput {
  description?: string;
  instructions_markdown?: string;
  public_permission?: SkillSharePermission | null;
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

export interface SkillShareUpdatePayload {
  user_shares?: {
    user_id: string;
    permission: SkillSharePermission;
  }[];
  group_shares?: {
    group_id: number;
    permission: SkillSharePermission;
  }[];
  public_permission?: SkillSharePermission | null;
}

export async function uploadUserSkillFiles(
  skillId: string,
  upload: File
): Promise<SkillEditableDetail> {
  const form = new FormData();
  form.append("upload", upload);
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
  path: string
): Promise<SkillEditableDetail> {
  const params = new URLSearchParams({ path });
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

export async function deleteUserSkill(skillId: string): Promise<void> {
  const res = await fetch(`/api/skills/custom/${skillId}`, {
    method: "DELETE",
  });
  await handle<void>(res);
}
