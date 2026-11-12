import { type Browser, type Page, expect, test } from "@playwright/test";
import {
  WORKER_USER_POOL_SIZE,
  workerUserCredentials,
} from "@tests/e2e/constants";
import { apiLogin } from "@tests/e2e/utils/auth";
import {
  createSkill,
  currentUserId,
  editSkillInstructions,
  setPublishing,
  shareSkillWithEditor,
  uniqueSkillName,
} from "@tests/e2e/utils/skills";
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
test("@exclusive a save waits for the author's Publish update", async ({
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
  const editor = await workerPage(browser, testInfo.workerIndex + 1);
  const name = uniqueSkillName("publish-update");
  const created = await createSkill(
    author.request,
    name,
    "Published instructions.",
    { publish: true }
  );
  await shareSkillWithEditor(
    author.request,
    created.id,
    await currentUserId(editor.request)
  );
  const saved = await editSkillInstructions(
    author.request,
    created.id,
    "Unpublished instructions."
  );
  expect(saved.current_version_number).toBe(created.current_version_number + 1);

  const editorSkills = new SkillsLibraryPage(editor);
  await editorSkills.goto();
  await editorSkills.expectCardUnpublishedChanges(name, true);
  await editorSkills.openSkill(name);
  await editorSkills.openVersionsTab();
  await editorSkills.expectUnpublishedChanges(true);
  await editorSkills.expectNoPublishUpdate();

  const authorSkills = new SkillsLibraryPage(author);
  await authorSkills.goto();
  await authorSkills.expectCardUnpublishedChanges(name, true);
  await authorSkills.openSkill(name);
  await authorSkills.openVersionsTab();
  await authorSkills.expectVersionStatus(
    created.current_version_number,
    "Published"
  );
  await authorSkills.expectVersionStatus(saved.current_version_number, "Draft");
  await authorSkills.publishUpdate();

  await authorSkills.expectToast(
    `Published version ${saved.current_version_number} to the organization.`
  );
  await authorSkills.expectUnpublishedChanges(false);
  await authorSkills.expectVersionStatus(
    saved.current_version_number,
    "Published"
  );
  await authorSkills.expectVersionStatus(
    created.current_version_number,
    "Superseded"
  );
  await authorSkills.closeDialog();
  await authorSkills.expectCardUnpublishedChanges(name, false);

  await author.context().close();
  await editor.context().close();
});
