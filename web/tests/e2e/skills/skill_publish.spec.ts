import { type Browser, type Page, expect, test } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import {
  createSkill,
  editSkillInstructions,
  setPublishing,
  uniqueSkillName,
} from "@tests/e2e/utils/skills";
import { SkillsLibraryPage } from "@tests/e2e/pages/SkillsLibraryPage";
import { AdminSkillsPage } from "@tests/e2e/pages/AdminSkillsPage";

async function authorPage(
  browser: Browser,
  workerIndex: number
): Promise<Page> {
  const context = await browser.newContext();
  const page = await context.newPage();
  await loginAsWorkerUser(page, workerIndex);
  return page;
}

// Both tests change the organization-wide Publishing setting, so they run alone.
test.describe("skill publishing", () => {
  test.beforeEach(async ({ page }) => {
    const settings = await (await page.request.get("/api/settings")).json();
    test.skip(
      settings?.onyx_craft_enabled !== true,
      "Onyx Craft is disabled in this environment"
    );
  });

  test.afterEach(async ({ page }) => {
    await setPublishing(page.request, "OPEN");
  });

  test("@exclusive an author publishes an update under Open", async ({
    browser,
    page: adminPage,
  }, testInfo) => {
    await setPublishing(adminPage.request, "OPEN");
    const author = await authorPage(browser, testInfo.workerIndex);
    try {
      const name = uniqueSkillName("publish-update");
      const created = await createSkill(
        author.request,
        name,
        "Published instructions.",
        { publish: true }
      );
      const saved = await editSkillInstructions(
        author.request,
        created.id,
        "Unpublished instructions."
      );
      expect(saved.current_version_number).toBe(
        created.current_version_number + 1
      );

      const skills = new SkillsLibraryPage(author);
      await skills.goto();
      await skills.expectCardUnpublishedChanges(name, true);
      await skills.openSkill(name);
      await skills.openVersionsTab();
      await skills.publishUpdate();

      await skills.expectToast(
        `Published version ${saved.current_version_number} to the organization.`
      );
      await skills.expectVersionStatus(
        saved.current_version_number,
        "Published"
      );
      await skills.closeDialog();
      await skills.expectCardUnpublishedChanges(name, false);
    } finally {
      await author.context().close();
    }
  });

  test("@exclusive an admin approves a publish update under Requires review", async ({
    browser,
    page: adminPage,
  }, testInfo) => {
    await setPublishing(adminPage.request, "REQUIRES_REVIEW");
    const author = await authorPage(browser, testInfo.workerIndex);
    try {
      const name = uniqueSkillName("publish-review");
      const created = await createSkill(
        author.request,
        name,
        "First version.",
        {
          publish: true,
        }
      );
      const saved = await editSkillInstructions(
        author.request,
        created.id,
        "Second version."
      );

      const skills = new SkillsLibraryPage(author);
      await skills.goto();
      await skills.openSkill(name);
      await skills.openVersionsTab();
      await skills.publishUpdate();
      await skills.expectToast(
        `Version ${saved.current_version_number} went to an admin for review.`
      );
      await skills.expectVersionStatus(
        saved.current_version_number,
        "Pending review"
      );

      const adminSkills = new AdminSkillsPage(adminPage);
      await adminSkills.goto();
      await adminSkills.expectRequest(
        name,
        `v${saved.current_version_number} · Update from v${created.current_version_number}`
      );
      await adminSkills.openReview(name);
      await adminSkills.expectReviewContent("Second version.");
      await adminSkills.approveInReview();
      await adminSkills.expectToast(
        `Published version ${saved.current_version_number} of ${name}.`
      );
      await adminSkills.expectNoRequest(name);
    } finally {
      await author.context().close();
    }
  });
});
