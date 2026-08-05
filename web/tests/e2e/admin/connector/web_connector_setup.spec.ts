import { test, expect } from "@playwright/test";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { ConnectorSetupPage } from "@tests/e2e/admin/connector/ConnectorSetupPage";
import { IndexingStatusPage } from "@tests/e2e/admin/connector/IndexingStatusPage";

/**
 * Full UI workflow for configuring a web connector: fill in the wizard,
 * create the connector, and verify it lands on the status page and its
 * detail page reflects the configuration.
 *
 * The connector is paused via the API immediately after creation so
 * background workers don't actually crawl the site, and deleted in
 * `afterEach` (looked up by name so cleanup also runs if the test fails
 * mid-way after creation).
 */
const DOCS_URL = "https://docs.onyx.app";

test.describe("Web connector setup", () => {
  let connectorName: string;
  let ccPairId: number | null = null;

  test.beforeEach(() => {
    connectorName = `Web Connector E2E ${Date.now()}`;
  });

  test.afterEach(async ({ page }) => {
    const apiClient = new OnyxApiClient(page.request);
    try {
      const idToDelete =
        ccPairId ?? (await apiClient.findCCPairByName("web", connectorName));
      ccPairId = null;
      if (idToDelete === null) return;

      // Deletion requires the connector to be paused first.
      await apiClient.pauseConnector(idToDelete);
      await apiClient.deleteCCPair(idToDelete);
    } catch (error) {
      console.warn(`Failed to clean up connector "${connectorName}": ${error}`);
    }
  });

  test("configures a web connector through the wizard", async ({ page }) => {
    const setupPage = new ConnectorSetupPage(page, "web");
    await setupPage.goto();

    await setupPage.connectorNameInput.fill(connectorName);
    await setupPage.textField("base_url").fill(DOCS_URL);
    await setupPage.selectField("web_connector_type").selectOption("recursive");

    await setupPage.submitAndWaitForCreation();

    // Pause via the API as soon as the connector exists so background
    // workers don't start crawling the site while the test finishes.
    const apiClient = new OnyxApiClient(page.request);
    ccPairId = await apiClient.findCCPairByName("web", connectorName);
    expect(ccPairId).not.toBeNull();
    await apiClient.pauseConnector(ccPairId!);

    // The new connector is listed under the (collapsed) Web source group.
    const statusPage = new IndexingStatusPage(page);
    await statusPage.expandSourceGroup("Web");
    await expect(statusPage.connectorRow(connectorName)).toBeVisible({
      timeout: 15_000,
    });

    // Clicking the row opens the detail page for the same cc-pair, which
    // shows the configured base URL.
    const openedCcPairId = await statusPage.openConnector(connectorName);
    expect(openedCcPairId).toBe(ccPairId);
    await expect(page.getByText(connectorName).first()).toBeVisible();
    await expect(page.getByText(DOCS_URL).first()).toBeVisible();
  });
});
