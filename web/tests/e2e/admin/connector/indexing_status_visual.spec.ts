import { test } from "@playwright/test";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { THEMES, setThemeBeforeNavigation } from "@tests/e2e/utils/theme";
import { IndexingStatusPage } from "@tests/e2e/admin/connector/IndexingStatusPage";

/**
 * Visual-regression coverage for the connector status page
 * (`/admin/indexing/status`).
 *
 * This page is deliberately excluded from the parallel admin-pages sweep (see
 * `VISUAL_REGRESSION_EXCLUDED_PATHS` in `admin_pages.spec.ts`): it renders the
 * list of existing connectors, and specs in the parallel `admin` project create
 * file connectors mid-run via `apiClient.createFileConnector(...)`, mutating the
 * table while the sweep screenshots it and producing flaky baseline diffs.
 *
 * The `@exclusive` tag moves this test into the serial `exclusive` project
 * (`workers: 1`, run as its own CI matrix job), so no other spec can add or
 * remove connectors while we snapshot. We seed exactly one paused file connector
 * via the API, screenshot the page in each theme, and tear the connector down
 * afterwards — keeping the rendered state deterministic.
 *
 * Auth comes from the `exclusive` project's `storageState`; each test gets a
 * fresh context, so no explicit login is needed.
 */
const CONNECTOR_NAME = "Visual Regression File Connector";
const FILE_SOURCE_GROUP = "File";

test.describe("Connector status page — visual @exclusive", () => {
  let ccPairId: number | null = null;

  test.beforeEach(async ({ page }) => {
    const apiClient = new OnyxApiClient(page.request);
    ccPairId = await apiClient.createFileConnector(CONNECTOR_NAME);
  });

  test.afterEach(async ({ page }) => {
    if (ccPairId === null) return;

    const apiClient = new OnyxApiClient(page.request);
    const idToDelete = ccPairId;
    ccPairId = null;

    // Let cleanup failures surface: a leaked connector would add a second
    // "File" row to the next theme test's screenshot, reintroducing exactly
    // the non-determinism this spec exists to remove.
    await apiClient.deleteCCPair(idToDelete);
  });

  for (const theme of THEMES) {
    test(`indexing status page – ${theme} mode`, async ({ page }) => {
      await setThemeBeforeNavigation(page, theme);

      const statusPage = new IndexingStatusPage(page);
      await statusPage.goto();
      await statusPage.waitForSourceGroup(FILE_SOURCE_GROUP);
      await statusPage.expectScreenshot(`admin-${theme}-indexing--status`);
    });
  }
});
