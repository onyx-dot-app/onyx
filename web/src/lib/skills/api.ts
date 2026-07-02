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
  public_permission?: SkillSharePermission | null;
  enabled?: boolean;
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

export async function deleteUserSkill(skillId: string): Promise<void> {
  const res = await fetch(`/api/skills/custom/${skillId}`, {
    method: "DELETE",
  });
  await handle<void>(res);
}
