/**
 * Thin client wrappers around the skills API.
 *
 * Pairs with `backend/onyx/server/features/skill/api.py`. All mutations bubble
 * server-side `OnyxError` detail strings as Error messages so callers can hand
 * them to `toast.error` directly.
 */

import type { CustomSkill, SkillSharePermission } from "@/lib/skills/types";

async function readErrorDetail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
    if (Array.isArray(body?.detail) && body.detail[0]?.msg)
      return body.detail[0].msg;
  } catch {
    // fall through
  }
  return `Request failed (${res.status})`;
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    throw new Error(await readErrorDetail(res));
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

export async function createCustomSkill(bundle: File): Promise<CustomSkill> {
  const form = new FormData();
  form.append("bundle", bundle);

  const res = await fetch("/api/skills/custom", {
    method: "POST",
    body: form,
  });
  return handle<CustomSkill>(res);
}

export interface PatchCustomSkillInput {
  name?: string;
  description?: string;
  instructions_markdown?: string;
  public_permission?: SkillSharePermission | null;
  enabled?: boolean;
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

export async function replaceUserSkillBundle(
  skillId: string,
  bundle: File
): Promise<CustomSkill> {
  const form = new FormData();
  form.append("bundle", bundle);
  const res = await fetch(`/api/skills/custom/${skillId}/bundle`, {
    method: "PUT",
    body: form,
  });
  return handle<CustomSkill>(res);
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
