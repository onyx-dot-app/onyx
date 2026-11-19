import { expect, test } from "@playwright/test";
import { InputBar } from "@tests/e2e/chat/InputBar";
import { CustomizePage } from "@tests/e2e/pages/CustomizePage";
import {
  createSkill,
  deleteSkill,
  uniqueSkillName,
} from "@tests/e2e/utils/skills";

const PLUGIN_ID = "00000000-0000-4000-8000-000000000001";

test.describe("Customize page", () => {
  test("old plugin and skill links open Customize with their query", async ({
    page,
  }) => {
    const cases: [string, string][] = [
      ["/app/plugins?from=bookmark", "/app/customize/plugins?from=bookmark"],
      [
        `/app/plugins/${PLUGIN_ID}?tab=integrations`,
        `/app/customize/plugins/${PLUGIN_ID}?tab=integrations`,
      ],
      ["/craft/v1/skills?q=1", "/app/customize/skills?q=1"],
      ["/craft/v1/skills/new?draft=abc", "/app/customize/skills/new?draft=abc"],
      [
        `/craft/v1/skills/edit/${PLUGIN_ID}`,
        `/app/customize/skills/${PLUGIN_ID}`,
      ],
      ["/craft/v1/plugins?connect=7", "/app/customize/integrations?connect=7"],
    ];
    for (const [from, to] of cases) {
      const response = await page.request.get(from, { maxRedirects: 0 });
      expect(response.status(), from).toBe(307);
      const target = new URL(
        response.headers()["location"] ?? "",
        "http://redirect.invalid"
      );
      expect(target.pathname + target.search, from).toBe(to);
    }
  });

  test("a skill shows in its group and turns off from the row menu", async ({
    page,
  }) => {
    const name = uniqueSkillName("customize");
    const created = await createSkill(page.request, name, "Do the task.");
    try {
      const customize = new CustomizePage(page);
      await customize.openFromSidebar();
      await customize.openTab("Skills");
      await customize.search(name);
      await customize.expectSkillInGroup(name, "Created by you");
      await customize.turnOffSkill(name);
      await customize.expectSkillOff(name);

      await customize.openTab("Integrations");
      await customize.openTab("Plugins");
    } finally {
      await deleteSkill(page.request, created.id);
    }
  });

  test("the @ menu in chat links to the skills page", async ({ page }) => {
    const name = uniqueSkillName("mention");
    const created = await createSkill(page.request, name, "Do the task.");
    try {
      await page.goto("/app");
      await new InputBar(page).openManageSkills(name);
      await expect(page).toHaveURL(/\/app\/customize\/skills$/);
    } finally {
      await deleteSkill(page.request, created.id);
    }
  });
});
