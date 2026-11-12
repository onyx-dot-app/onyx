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
  instructions: string
): Promise<CreatedSkill> {
  const res = await request.post("/api/skills/custom/editor", {
    multipart: {
      name,
      description: `E2E skill ${name}`,
      instructions_markdown: instructions,
      auto_enable: "true",
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
