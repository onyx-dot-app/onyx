import { test, expect } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { THEMES, setThemeBeforeNavigation } from "@tests/e2e/utils/theme";
import { expectScreenshot } from "@tests/e2e/utils/visualRegression";

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
 */
const CONNECTOR_NAME = "Visual Regression File Connector";

test.describe("Connector status page — visual @exclusive", () => {
  let ccPairId: number | null = null;

  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");

    const apiClient = new OnyxApiClient(page.request);
    ccPairId = await apiClient.createFileConnector(CONNECTOR_NAME);
  });

  test.afterEach(async ({ page }) => {
    if (ccPairId === null) return;

    const apiClient = new OnyxApiClient(page.request);
    try {
      await apiClient.deleteCCPair(ccPairId);
    } catch (error) {
      console.warn(`Failed to delete test connector ${ccPairId}: ${error}`);
    } finally {
      ccPairId = null;
    }
  });

  for (const theme of THEMES) {
    test(`indexing status page – ${theme} mode`, async ({ page }) => {
      await setThemeBeforeNavigation(page, theme);

      await page.goto("/admin/indexing/status");

      await expect(page.locator('[aria-label="admin-page-title"]')).toBeVisible(
        { timeout: 10000 }
      );

      // Wait for the seeded connector's source group ("File", the display name
      // for the `file` source) to render so we don't snapshot the loading
      // skeleton. The group row is shown collapsed by default.
      await expect(page.getByText("File", { exact: true }).first()).toBeVisible(
        { timeout: 15000 }
      );

      await page.waitForLoadState("networkidle");

      await expectScreenshot(page, {
        name: `admin-${theme}-indexing--status`,
        mask: [
          '[data-testid="admin-date-range-selector-button"]',
          '[data-column-id="updated_at"]',
        ],
      });
    });
  }
});
