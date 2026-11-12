import { type Browser, type Page, test } from "@playwright/test";
import {
  WORKER_USER_POOL_SIZE,
  workerUserCredentials,
} from "@tests/e2e/constants";
import { apiLogin } from "@tests/e2e/utils/auth";
import {
  createSkill,
  editSkillInstructions,
  setPublishing,
  uniqueSkillName,
} from "@tests/e2e/utils/skills";
import { AdminCraftPreferencesPage } from "@tests/e2e/pages/AdminCraftPreferencesPage";
import { AdminSkillsPage } from "@tests/e2e/pages/AdminSkillsPage";
import { SkillsLibraryPage } from "@tests/e2e/pages/SkillsLibraryPage";

async function workerPage(browser: Browser, index: number): Promise<Page> {
  const context = await browser.newContext({
    storageState: { cookies: [], origins: [] },
  });
  const page = await context.newPage();
  const { email, password } = workerUserCredentials(
    index % WORKER_USER_POOL_SIZE
  );
  await apiLogin(page, email, password);
  return page;
}

// Changes the organization-wide Publishing setting, so it runs alone.
test("@exclusive an admin approves a publish update under Requires review", async ({
  browser,
  page: adminPage,
}, testInfo) => {
  const settings = await (await adminPage.request.get("/api/settings")).json();
  test.skip(
    settings?.onyx_craft_enabled !== true,
    "Onyx Craft is disabled in this environment"
  );
  await setPublishing(adminPage.request, "OPEN");
  const author = await workerPage(browser, testInfo.workerIndex);
  const member = await workerPage(browser, testInfo.workerIndex + 1);
  const name = uniqueSkillName("review");
  const created = await createSkill(author.request, name, "First version.", {
    publish: true,
  });

  try {
    const preferences = new AdminCraftPreferencesPage(adminPage);
    await preferences.goto();
    await preferences.setPublishing("Requires review");

    const saved = await editSkillInstructions(
      author.request,
      created.id,
      "Second version."
    );
    const authorSkills = new SkillsLibraryPage(author);
    await authorSkills.goto();
    await authorSkills.openSkill(name);
    await authorSkills.openVersionsTab();
    await authorSkills.publishUpdate();
    await authorSkills.expectToast(
      `Version ${saved.current_version_number} went to an admin for review.`
    );
    await authorSkills.expectWaitingForReview();
    await authorSkills.expectVersionStatus(
      saved.current_version_number,
      "Pending review"
    );

    const memberSkills = new SkillsLibraryPage(member);
    await memberSkills.goto();
    await memberSkills.openSkill(name);
    await memberSkills.expectInstructions("First version.");
    await memberSkills.closeDialog();

    const adminSkills = new AdminSkillsPage(adminPage);
    await adminSkills.goto();
    await adminSkills.expectRequest(name, "Update from version 1");
    await adminSkills.approve(name);
    await adminSkills.expectToast(
      `Published version ${saved.current_version_number} of ${name}.`
    );
    await adminSkills.expectNoRequest(name);

    await memberSkills.goto();
    await memberSkills.openSkill(name);
    await memberSkills.expectInstructions("Second version.");
  } finally {
    await setPublishing(adminPage.request, "OPEN");
    await author.context().close();
    await member.context().close();
  }
});
