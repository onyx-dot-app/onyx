import { type APIRequestContext, expect } from "@playwright/test";

export interface CreatedSkill {
  id: string;
  name: string;
  current_version_id: string;
  current_version_number: number;
}

/** A skill name no other test run uses. */
export function uniqueSkillName(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}${Math.random()
    .toString(36)
    .slice(2, 6)}`;
}

export async function createSkill(
  request: APIRequestContext,
  name: string,
  instructions: string,
  options: { publish?: boolean } = {}
): Promise<CreatedSkill> {
  const res = await request.post("/api/skills/custom/editor", {
    multipart: {
      name,
      description: `E2E skill ${name}`,
      instructions_markdown: instructions,
      auto_enable: "true",
      ...(options.publish
        ? { sharing: JSON.stringify({ public_permission: "VIEWER" }) }
        : {}),
    },
  });
  expect(res.ok(), await res.text()).toBeTruthy();
  return res.json();
}

export async function editSkillInstructions(
  request: APIRequestContext,
  skillId: string,
  instructions: string
): Promise<CreatedSkill> {
  const res = await request.patch(`/api/skills/custom/${skillId}`, {
    data: { instructions_markdown: instructions },
  });
  expect(res.ok(), await res.text()).toBeTruthy();
  return res.json();
}

export async function shareSkillWithEditor(
  request: APIRequestContext,
  skillId: string,
  userId: string
): Promise<void> {
  const res = await request.patch(`/api/skills/custom/${skillId}/share`, {
    data: { user_shares: [{ user_id: userId, permission: "EDITOR" }] },
  });
  expect(res.ok(), await res.text()).toBeTruthy();
}

export type PublishingPolicy = "OPEN" | "REQUIRES_REVIEW" | "OFF";

/** Set the admin Publishing setting. `adminRequest` must be an admin session. */
export async function setPublishing(
  adminRequest: APIRequestContext,
  policy: PublishingPolicy
): Promise<void> {
  const res = await adminRequest.patch("/api/admin/settings", {
    data: { plugin_publishing: policy },
  });
  expect(res.ok(), await res.text()).toBeTruthy();
}

export async function currentUserId(
  request: APIRequestContext
): Promise<string> {
  const res = await request.get("/api/me");
  expect(res.ok(), await res.text()).toBeTruthy();
  return (await res.json()).id;
}
