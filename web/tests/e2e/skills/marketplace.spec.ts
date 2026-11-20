import { expect, test } from "@playwright/test";
import { MarketplacesPage } from "@tests/e2e/pages/MarketplacesPage";
import { FakeMarketplacesApi } from "@tests/e2e/utils/marketplaces";

test.describe("GitHub marketplaces", () => {
  test("add a marketplace from a repository, then sync it", async ({
    page,
  }) => {
    const api = await FakeMarketplacesApi.install(page);
    const marketplaces = new MarketplacesPage(page);

    await marketplaces.openAddDialog();
    await marketplaces.enterSource({
      repository: "acme/plugins",
      folder: "catalog",
      ref: "main",
    });
    await marketplaces.expectResolved([
      "acme/plugins",
      "catalog",
      "main",
      "review-kit",
      "Will install",
      "Not supported in Onyx.",
    ]);
    await marketplaces.add();

    await expect(page).toHaveURL(/\/app\/customize\/plugins\/marketplaces$/);
    await marketplaces.expectRow("acme/plugins", [
      "acme/plugins/catalog@main",
      "Personal",
      "1 plugin",
      "Synced",
    ]);

    await marketplaces.syncNow("acme/plugins");
    await marketplaces.expectRow("acme/plugins", ["2 plugins", "Synced"]);
    expect(api.syncRequests).toHaveLength(1);
  });
});
