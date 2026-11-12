import { expect, test } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import {
  createSkill,
  editSkillInstructions,
  uniqueSkillName,
} from "@tests/e2e/utils/skills";
import { SkillsLibraryPage } from "@tests/e2e/pages/SkillsLibraryPage";

test.use({ storageState: { cookies: [], origins: [] } });

test("restoring an old version adds a new current version", async ({
  page,
}, testInfo) => {
  await loginAsWorkerUser(page, testInfo.workerIndex);
  const settings = await (await page.request.get("/api/settings")).json();
  test.skip(
    settings?.onyx_craft_enabled !== true,
    "Onyx Craft is disabled in this environment"
  );

  const name = uniqueSkillName("versions");
  const created = await createSkill(page.request, name, "First instructions.");
  const edited = await editSkillInstructions(
    page.request,
    created.id,
    "Second instructions."
  );
  expect(edited.current_version_number).toBe(
    created.current_version_number + 1
  );

  const skills = new SkillsLibraryPage(page);
  await skills.goto();
  await skills.expectCardVersion(name, edited.current_version_number);
  await skills.openSkill(name);
  await skills.openVersionsTab();
  await skills.expectCurrentVersion(edited.current_version_number);
  await skills.expectNoRestore(edited.current_version_number);

  await skills.restoreVersion(created.current_version_number);

  const restoredNumber = edited.current_version_number + 1;
  await skills.expectToast(
    `Restored version ${created.current_version_number} as version ${restoredNumber}.`
  );
  await skills.expectCurrentVersion(restoredNumber);
  await skills.closeDialog();
  await skills.expectCardVersion(name, restoredNumber);
});
