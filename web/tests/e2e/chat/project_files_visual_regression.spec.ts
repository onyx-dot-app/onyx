import { expect, test, type Locator, type Page } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { expectElementScreenshot } from "@tests/e2e/utils/visualRegression";

const TEST_PREFIX = "E2E-PROJECT-FILES-VISUAL";
const LONG_FILE_NAME =
  "CSE_202_Final_Project_Solution_Regression_Check_Long_Name.txt";
const FILE_CONTENT = "Visual regression test content for long filename cards.";

let projectId: number | null = null;

function getFilesSection(page: Page): Locator {
  return page
    .locator("div")
    .filter({ has: page.getByRole("button", { name: "Add Files" }) })
    .filter({ hasText: "Chats in this project can access these files." })
    .first();
}

async function uploadFileToProject(
  page: Page,
  targetProjectId: number,
  fileName: string,
  content: string
): Promise<void> {
  const response = await page.request.post("/api/user/projects/file/upload", {
    multipart: {
      project_id: String(targetProjectId),
      files: {
        name: fileName,
        mimeType: "text/plain",
        buffer: Buffer.from(content, "utf-8"),
      },
    },
  });

  expect(response.ok()).toBeTruthy();
}

test.describe("Project Files visual regression", () => {
  test.beforeAll(async ({ browser }, workerInfo) => {
    const context = await browser.newContext();
    const page = await context.newPage();

    await loginAsWorkerUser(page, workerInfo.workerIndex);
    const client = new OnyxApiClient(page.request);

    projectId = await client.createProject(`${TEST_PREFIX}-${Date.now()}`);
    await uploadFileToProject(page, projectId, LONG_FILE_NAME, FILE_CONTENT);

    await context.close();
  });

  test.afterAll(async ({ browser }, workerInfo) => {
    if (!projectId) {
      return;
    }

    const context = await browser.newContext();
    const page = await context.newPage();

    await loginAsWorkerUser(page, workerInfo.workerIndex);
    const client = new OnyxApiClient(page.request);
    await client.deleteProject(projectId);

    await context.close();
  });

  test.beforeEach(async ({ page }, workerInfo) => {
    test.skip(
      projectId === null,
      "Project setup failed; skipping project file visual regression"
    );

    await page.context().clearCookies();
    await loginAsWorkerUser(page, workerInfo.workerIndex);
    await page.goto(`/app?projectId=${projectId}`);
    await page.waitForLoadState("networkidle");
    await expect(
      page.getByText("Chats in this project can access these files.")
    ).toBeVisible();
  });

  test("long underscore filename stays visually contained in file card", async ({
    page,
  }) => {
    const filesSection = getFilesSection(page);
    await expect(filesSection).toBeVisible();

    const fileTitle = filesSection
      .locator(".opal-content-md-title")
      .filter({ hasText: LONG_FILE_NAME })
      .first();
    await expect(fileTitle).toBeVisible();

    const iconWrapper = filesSection
      .locator(".attachment-button__icon-wrapper")
      .first();
    await expect(iconWrapper).toBeVisible();

    const geometry = await iconWrapper.evaluate((iconEl) => {
      let cardEl: HTMLElement | null = iconEl.parentElement;

      while (cardEl) {
        const style = window.getComputedStyle(cardEl);
        const hasBorder =
          parseFloat(style.borderTopWidth) > 0 ||
          parseFloat(style.borderLeftWidth) > 0;
        const hasRadius = parseFloat(style.borderTopLeftRadius) > 0;

        if (hasBorder && hasRadius) {
          break;
        }
        cardEl = cardEl.parentElement;
      }

      if (!cardEl) {
        return null;
      }

      const iconRect = iconEl.getBoundingClientRect();
      const cardRect = cardEl.getBoundingClientRect();

      return {
        iconLeft: iconRect.left,
        iconRight: iconRect.right,
        cardLeft: cardRect.left,
        cardRight: cardRect.right,
      };
    });

    expect(geometry).not.toBeNull();
    expect(geometry!.iconLeft).toBeGreaterThanOrEqual(geometry!.cardLeft - 1);
    expect(geometry!.iconRight).toBeLessThanOrEqual(geometry!.cardRight + 1);

    await expectElementScreenshot(filesSection, {
      name: "project-files-long-underscore-filename",
    });
  });
});
