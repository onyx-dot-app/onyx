import { test } from "@playwright/test";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { AdminDocumentSetsPage } from "@tests/e2e/pages/AdminDocumentSetsPage";

/**
 * The document set list's search matches each set's name, description and
 * connectors. Every name carries a unique suffix, so a query that includes it
 * cannot match sets that specs running in parallel create.
 */
test.describe("Document set search", () => {
  const suffix = `${Date.now()}`;
  const handbookSet = `Handbook ${suffix}`;
  const supportSet = `Support ${suffix}`;
  const ccPairIds: number[] = [];
  const documentSetIds: number[] = [];

  test.beforeEach(async ({ page }) => {
    const apiClient = new OnyxApiClient(page.request);
    const handbookFiles = await apiClient.createFileConnector(
      `Handbook Files ${suffix}`
    );
    const ticketExports = await apiClient.createFileConnector(
      `Ticket Exports ${suffix}`
    );
    ccPairIds.push(handbookFiles, ticketExports);
    documentSetIds.push(
      await apiClient.createDocumentSet(handbookSet, [handbookFiles]),
      await apiClient.createDocumentSet(supportSet, [ticketExports])
    );
  });

  test.afterEach(async ({ page }) => {
    const apiClient = new OnyxApiClient(page.request);
    for (const documentSetId of documentSetIds.splice(0)) {
      // The backend refuses to delete a set while it syncs.
      await apiClient.waitForDocumentSetSync(documentSetId);
      await apiClient.deleteDocumentSet(documentSetId);
    }
    for (const ccPairId of ccPairIds.splice(0)) {
      await apiClient.deleteCCPair(ccPairId);
    }
  });

  test("finds sets by name and by connector", async ({ page }) => {
    const documentSets = new AdminDocumentSetsPage(page);
    await documentSets.goto();

    await documentSets.search(suffix);
    await documentSets.expectListed(handbookSet);
    await documentSets.expectListed(supportSet);

    // Only the support set holds the "Ticket Exports" connector.
    await documentSets.search(`ticket exports ${suffix}`);
    await documentSets.expectListed(supportSet);
    await documentSets.expectNotListed(handbookSet);

    await documentSets.search(`missing ${suffix}`);
    await documentSets.expectNoResults();
  });
});
