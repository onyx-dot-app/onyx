import { test } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { AdminConnectorDetailPage } from "@tests/e2e/pages/AdminConnectorDetailPage";
import { ConnectorEditPage } from "@tests/e2e/pages/ConnectorEditPage";

test.describe("Connector edit through a plan", () => {
  let ccPairId: number | null = null;
  let connectorName = "";

  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");
    connectorName = `E2E Edit ${Date.now()}`;
    ccPairId = await new OnyxApiClient(page.request).createFileConnector(
      connectorName
    );
  });

  test.afterEach(async ({ page }) => {
    if (ccPairId === null) return;
    try {
      await new OnyxApiClient(page.request).deleteCCPair(ccPairId);
    } catch (error) {
      console.warn(`Failed to delete test connector ${ccPairId}: ${error}`);
    }
    ccPairId = null;
  });

  test("renames the connector from the pre-filled form", async ({ page }) => {
    const id = ccPairId ?? -1;
    const detailPage = new AdminConnectorDetailPage(page);
    const editPage = new ConnectorEditPage(page);

    await detailPage.goto(id);
    await detailPage.openEditForm();
    await editPage.expectLoaded(connectorName);

    const newName = `${connectorName} renamed`;
    await editPage.setName(newName);
    await editPage.reviewChanges();
    await editPage.expectPlanChanges(/Changed: .*name/);
    await editPage.apply();

    await editPage.expectApplied(id);
    await detailPage.expectName(newName);
  });

  test("adds a file and indexes it on apply", async ({ page }) => {
    const id = ccPairId ?? -1;
    const editPage = new ConnectorEditPage(page);

    await editPage.goto("file", id);
    await editPage.expectLoaded(connectorName);
    await editPage.addFile(`e2e-edit-${Date.now()}.txt`, "Edit flow content.");
    await editPage.reviewChanges();
    await editPage.expectPlanChanges(/Changed: /);
    await editPage.apply();

    await editPage.expectApplied(id);
  });
});
