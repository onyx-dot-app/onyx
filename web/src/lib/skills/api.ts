/**
 * Thin client wrappers around the skills API.
 *
 * Pairs with `backend/onyx/server/features/skill/api.py`. All mutations bubble
 * server-side `OnyxError` detail strings as Error messages so callers can hand
 * them to `toast.error` directly.
 */

import type {
  CustomSkill,
  SkillsList,
} from "@/refresh-pages/admin/SkillsPage/interfaces";

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
// Reads — both list endpoints are served by useSWR; these are kept here for
// places that need an imperative fetch (e.g. after a mutation that touches a
// non-list cache).
// ---------------------------------------------------------------------------

export async function fetchAdminSkills(): Promise<SkillsList> {
  const res = await fetch("/api/admin/skills");
  return handle<SkillsList>(res);
}

export async function fetchUserSkills(): Promise<SkillsList> {
  const res = await fetch("/api/skills");
  return handle<SkillsList>(res);
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

export interface CreateCustomSkillInput {
  bundle: File;
  is_public: boolean;
  group_ids: number[];
}

export async function createCustomSkill(
  input: CreateCustomSkillInput
): Promise<CustomSkill> {
  const form = new FormData();
  form.append("is_public", String(input.is_public));
  form.append("group_ids", JSON.stringify(input.group_ids));
  form.append("bundle", input.bundle);

  const res = await fetch("/api/admin/skills/custom", {
    method: "POST",
    body: form,
  });
  return handle<CustomSkill>(res);
}

export interface PatchCustomSkillInput {
  is_public?: boolean;
  enabled?: boolean;
}

export async function patchCustomSkill(
  skillId: string,
  patch: PatchCustomSkillInput
): Promise<CustomSkill> {
  const res = await fetch(`/api/admin/skills/custom/${skillId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return handle<CustomSkill>(res);
}

export async function replaceCustomSkillBundle(
  skillId: string,
  bundle: File
): Promise<CustomSkill> {
  const form = new FormData();
  form.append("bundle", bundle);
  const res = await fetch(`/api/admin/skills/custom/${skillId}/bundle`, {
    method: "PUT",
    body: form,
  });
  return handle<CustomSkill>(res);
}

export async function replaceCustomSkillGrants(
  skillId: string,
  groupIds: number[]
): Promise<CustomSkill> {
  const res = await fetch(`/api/admin/skills/custom/${skillId}/grants`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ group_ids: groupIds }),
  });
  return handle<CustomSkill>(res);
}

export async function deleteCustomSkill(skillId: string): Promise<void> {
  const res = await fetch(`/api/admin/skills/custom/${skillId}`, {
    method: "DELETE",
  });
  await handle<void>(res);
}
