import { expect, test } from "@tests/e2e/fixtures/eeFeatures";
import { AdminServiceStatusPage } from "@tests/e2e/pages/AdminServiceStatusPage";

test.use({ storageState: "admin_auth.json" });

test.describe("service status", () => {
  test("an admin sees the search cluster's nodes and indexes", async ({
    page,
    eeEnabled,
  }) => {
    test.skip(!eeEnabled, "Requires an active Enterprise license");
    const status = new AdminServiceStatusPage(page);
    await status.goto();

    await expect(status.nodes.first()).toBeVisible();
    await expect(status.indexes.first()).toBeVisible();
    await expect(status.clusterHeading).toBeVisible();

    await status.refresh();
    await expect(status.nodes.first()).toBeVisible();
  });
});
