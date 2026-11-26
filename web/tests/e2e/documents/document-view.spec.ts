import { test } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { DocumentViewPage } from "@tests/e2e/pages/DocumentViewPage";

test.describe("Document view", () => {
  test("shows an ingested document that has no link", async ({ page }) => {
    await loginAs(page, "admin");
    const title = `E2E document ${Date.now()}`;
    const text = `Body of ${title}`;
    const documentId = await new OnyxApiClient(page.request).ingestDocument(
      title,
      text
    );

    const documentView = new DocumentViewPage(page);
    await documentView.goto(documentId);
    await documentView.expectDocument(title, text);
  });

  test("shows the not-found state for an unknown or missing id", async ({
    page,
  }) => {
    await loginAs(page, "admin");

    const documentView = new DocumentViewPage(page);
    await documentView.goto(`missing-${Date.now()}`);
    await documentView.expectNotFound();
    await documentView.gotoWithoutId();
    await documentView.expectNotFound();
  });
});
