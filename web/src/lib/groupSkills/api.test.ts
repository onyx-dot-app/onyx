import {
  getUserGroupSkills,
  setGroupInstallationPolicy,
} from "@/lib/groupSkills/api";
import type { UserGroupSkills } from "@/lib/groupSkills/types";

const marketplaceId = "10000000-0000-4000-8000-000000000001";
const skillId = "20000000-0000-4000-8000-000000000002";
const snapshot = {
  marketplaces: [
    {
      marketplace_id: marketplaceId,
      name: "Company tools",
      permission: "VIEWER",
      company_installation_policy: "AVAILABLE",
      group_installation_policy: "NOT_AVAILABLE",
      effective_installation_policy: "NOT_AVAILABLE",
      following_skill_count: 3,
      can_edit: true,
    },
  ],
  skills: [
    {
      skill_id: skillId,
      name: "detached",
      description: "Own access",
      source: "COMPANY_MARKETPLACE",
      marketplace_id: marketplaceId,
      marketplace_name: "Company tools",
      permission: "EDITOR",
      company_installation_policy: "REQUIRED",
      group_installation_policy: null,
      effective_installation_policy: "REQUIRED",
      can_edit: false,
    },
  ],
} satisfies UserGroupSkills;

afterEach(() => jest.restoreAllMocks());

test("reads group settings and sends null to inherit", async () => {
  // GET the list, then PUT a skill reset and a marketplace setting.
  const fetch = jest
    .spyOn(global, "fetch")
    .mockImplementation(async () => Response.json(snapshot));
  await expect(getUserGroupSkills(7)).resolves.toEqual(snapshot);
  expect(fetch).toHaveBeenNthCalledWith(
    1,
    "/api/manage/admin/user-group/7/skills"
  );
  await setGroupInstallationPolicy({
    groupId: 7,
    target: { kind: "skill", id: skillId },
    installationPolicy: null,
  });
  await setGroupInstallationPolicy({
    groupId: 7,
    target: { kind: "marketplace", id: marketplaceId },
    installationPolicy: "NOT_AVAILABLE",
  });
  expect(fetch).toHaveBeenNthCalledWith(
    2,
    `/api/manage/admin/user-group/7/skills/${skillId}/installation-policy`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ installation_policy: null }),
    }
  );
  expect(fetch).toHaveBeenNthCalledWith(
    3,
    `/api/manage/admin/user-group/7/marketplaces/${marketplaceId}/installation-policy`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ installation_policy: "NOT_AVAILABLE" }),
    }
  );
});

test("rejects an unknown source", async () => {
  jest.spyOn(global, "fetch").mockResolvedValue(
    Response.json({
      ...snapshot,
      skills: [{ ...snapshot.skills[0], source: "OTHER" }],
    })
  );
  await expect(getUserGroupSkills(7)).rejects.toThrow();
});
