import { test } from "@playwright/test";
import { createSkill, uniqueSkillName } from "@tests/e2e/utils/skills";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { AdminSkillsPage } from "@tests/e2e/pages/AdminSkillsPage";

test.describe("skill group access", () => {
  test("an admin sets a group policy and filters the Skills page by the group", async ({
    page,
  }) => {
    const api = new OnyxApiClient(page.request);
    const groupName = uniqueSkillName("e2e-group");
    const groupId = await api.createUserGroup(groupName);
    try {
      const name = uniqueSkillName("group-access");
      const other = uniqueSkillName("group-access-other");
      await createSkill(page.request, name, "Group instructions.", {
        publish: true,
      });
      await createSkill(page.request, other, "Other instructions.", {
        publish: true,
      });

      const skills = new AdminSkillsPage(page);
      await skills.goto();
      await skills.openSharing(name);
      await skills.setGroupPolicy(groupName, /^Required/);
      await skills.expectCardText(name, `Groups: ${groupName}: Required`);

      await skills.filterByGroup(groupName);
      await skills.expectCardShown(name, true);
      await skills.expectCardShown(other, false);
    } finally {
      await api.deleteUserGroup(groupId).catch(() => undefined);
    }
  });
});
