/**
 * Thin client wrappers around the skills API.
 *
 * Pairs with `backend/onyx/server/features/skill/api.py`. All mutations bubble
 * server-side `OnyxError` detail strings as Error messages so callers can hand
 * them to `toast.error` directly.
 */

import type {
  CustomSkill,
  GitHubSkillsPreview,
  SkillBundleContents,
  SkillEditableDetail,
  SkillSharePermission,
} from "@/lib/skills/types";
import { FetchError } from "@/lib/fetcher";

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      body = undefined;
    }
    const detail =
      body && typeof body === "object" && "detail" in body
        ? body.detail
        : undefined;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail) &&
            detail[0] &&
            typeof detail[0] === "object" &&
            "msg" in detail[0] &&
            typeof detail[0].msg === "string"
          ? detail[0].msg
          : `Request failed (${res.status})`;
    throw new FetchError(message, res.status, body);
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
  repository: string,
  paths: string[]
): Promise<CustomSkill[]> {
  const res = await fetch("/api/skills/github/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repository, paths }),
  });
  return handle<CustomSkill[]>(res);
}

export interface CreateCustomSkillInput {
  name: string;
  description: string;
  instructions_markdown: string;
}

export async function createCustomSkillFromEditor(
  input: CreateCustomSkillInput,
  upload?: File
): Promise<SkillEditableDetail> {
  const form = new FormData();
  form.append("name", input.name);
  form.append("description", input.description);
  form.append("instructions_markdown", input.instructions_markdown);
  if (upload) form.append("upload", upload);

  const res = await fetch("/api/skills/custom/editor", {
    method: "POST",
    body: form,
  });
  return handle<SkillEditableDetail>(res);
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
