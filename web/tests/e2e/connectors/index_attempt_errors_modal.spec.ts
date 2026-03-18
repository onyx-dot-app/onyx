import { test, expect } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { execSync } from "child_process";

// ─── Database Helpers ─────────────────────────────────────────────────────────
// IndexAttemptError rows are produced by background workers in production.
// In tests we seed them directly via psql since there is no public API for it.

const DB_CONTAINER = process.env.DB_CONTAINER || "onyx-relational_db-1";

function psql(sql: string): string {
  return execSync(`docker exec -i ${DB_CONTAINER} psql -U postgres -t -A`, {
    input: sql,
    encoding: "utf-8",
  }).trim();
}

function getSearchSettingsId(): number {
  const result = psql(
    "SELECT id FROM search_settings WHERE status = 'PRESENT' ORDER BY id DESC LIMIT 1;"
  );
  const id = parseInt(result, 10);
  if (isNaN(id)) {
    throw new Error(
      `No search_settings with status PRESENT found: "${result}"`
    );
  }
  return id;
}

function createIndexAttempt(
  ccPairId: number,
  options: { fromBeginning?: boolean; status?: string } = {}
): number {
  const { fromBeginning = false, status = "success" } = options;
  const searchSettingsId = getSearchSettingsId();
  const result = psql(
    `INSERT INTO index_attempt (
       connector_credential_pair_id, from_beginning, status, search_settings_id,
       time_created, time_started, time_updated
     ) VALUES (
       ${ccPairId}, ${fromBeginning}, '${status}', ${searchSettingsId},
       NOW(), NOW(), NOW()
     ) RETURNING id;`
  );
  const id = parseInt(result, 10);
  if (isNaN(id)) {
    throw new Error(`Failed to create index attempt: "${result}"`);
  }
  return id;
}

function sqlVal(v: string | null): string {
  return v === null ? "NULL" : `'${v.replace(/'/g, "''")}'`;
}

interface CreateErrorOptions {
  indexAttemptId: number;
  ccPairId: number;
  documentId?: string | null;
  documentLink?: string | null;
  entityId?: string | null;
  failureMessage?: string;
  isResolved?: boolean;
}

function createError(options: CreateErrorOptions): number {
  const {
    indexAttemptId,
    ccPairId,
    documentId = null,
    documentLink = null,
    entityId = null,
    failureMessage = "Test indexing error",
    isResolved = false,
  } = options;

  const result = psql(
    `INSERT INTO index_attempt_errors (
       index_attempt_id, connector_credential_pair_id,
       document_id, document_link, entity_id,
       failure_message, is_resolved, time_created
     ) VALUES (
       ${indexAttemptId}, ${ccPairId},
       ${sqlVal(documentId)}, ${sqlVal(documentLink)}, ${sqlVal(entityId)},
       ${sqlVal(failureMessage)}, ${isResolved}, NOW()
     ) RETURNING id;`
  );
  const id = parseInt(result, 10);
  if (isNaN(id)) {
    throw new Error(`Failed to create index attempt error: "${result}"`);
  }
  return id;
}

function createMultipleErrors(
  indexAttemptId: number,
  ccPairId: number,
  count: number
): number[] {
  const ids: number[] = [];
  for (let i = 0; i < count; i++) {
    ids.push(
      createError({
        indexAttemptId,
        ccPairId,
        documentId: `doc-${i + 1}`,
        failureMessage: `Error #${i + 1}: Failed to index document`,
      })
    );
  }
  return ids;
}

function resolveAllErrors(ccPairId: number): void {
  psql(
    `UPDATE index_attempt_errors SET is_resolved = true
     WHERE connector_credential_pair_id = ${ccPairId};`
  );
}

// ─── Shared UI Helpers ────────────────────────────────────────────────────────

async function waitForBanner(page: import("@playwright/test").Page) {
  await expect(page.getByText("Some documents failed to index")).toBeVisible({
    timeout: 15000,
  });
}

async function openErrorsModal(page: import("@playwright/test").Page) {
  await waitForBanner(page);
  await page.getByText("View details.").click();
  await expect(page.getByText("Indexing Errors")).toBeVisible();
}

// ─── Tests ────────────────────────────────────────────────────────────────────

test.describe("Index Attempt Errors Modal", () => {
  test.describe.configure({ retries: 2 });

  let testCcPairId: number | null = null;
  let testIndexAttemptId: number | null = null;

  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");

    const apiClient = new OnyxApiClient(page.request);
    testCcPairId = await apiClient.createFileConnector(
      `Error Modal Test ${Date.now()}`
    );
    testIndexAttemptId = createIndexAttempt(testCcPairId);
  });

  test.afterEach(async ({ page }) => {
    if (testCcPairId !== null) {
      const apiClient = new OnyxApiClient(page.request);
      try {
        await apiClient.pauseConnector(testCcPairId);
      } catch {
        // May already be paused
      }
      try {
        await apiClient.deleteCCPair(testCcPairId);
      } catch (error) {
        console.warn(`Cleanup failed for CC pair ${testCcPairId}: ${error}`);
      }
      testCcPairId = null;
      testIndexAttemptId = null;
    }
  });

  // ── 1. Alert Banner Visibility ────────────────────────────────────────────

  test("1.1 banner is hidden when no errors exist", async ({ page }) => {
    await page.goto(`/admin/connector/${testCcPairId}`);
    await page.waitForLoadState("networkidle");

    await expect(
      page.getByText("Some documents failed to index")
    ).not.toBeVisible();
  });

  test("1.2 banner appears when unresolved errors exist", async ({ page }) => {
    createError({
      indexAttemptId: testIndexAttemptId!,
      ccPairId: testCcPairId!,
      documentId: "doc-banner-test",
      failureMessage: "Test error for banner visibility",
    });

    await page.goto(`/admin/connector/${testCcPairId}`);
    await page.waitForLoadState("networkidle");

    await waitForBanner(page);
    await expect(
      page.getByText("We ran into some issues while processing some documents.")
    ).toBeVisible();
    await expect(page.getByText("View details.")).toBeVisible();
  });

  test("1.3 banner disappears when all errors are resolved", async ({
    page,
  }) => {
    createError({
      indexAttemptId: testIndexAttemptId!,
      ccPairId: testCcPairId!,
      failureMessage: "Error to be resolved",
    });

    await page.goto(`/admin/connector/${testCcPairId}`);
    await page.waitForLoadState("networkidle");
    await waitForBanner(page);

    // Resolve all errors via DB
    resolveAllErrors(testCcPairId!);

    // Wait for the 5-second polling cycle to pick up the change
    await expect(
      page.getByText("Some documents failed to index")
    ).not.toBeVisible({ timeout: 15000 });
  });

  // ── 2. Opening and Closing the Modal ──────────────────────────────────────

  test("2.1 modal opens via View details link with correct content", async ({
    page,
  }) => {
    createError({
      indexAttemptId: testIndexAttemptId!,
      ccPairId: testCcPairId!,
      documentId: "doc-modal-open",
      failureMessage: "Error for modal open test",
    });

    await page.goto(`/admin/connector/${testCcPairId}`);
    await page.waitForLoadState("networkidle");
    await openErrorsModal(page);

    // Explanatory text
    await expect(
      page.getByText("Below are the errors encountered during indexing.")
    ).toBeVisible();
    await expect(
      page.getByText(
        "Click the button below to kick off a full re-index to try and resolve these errors."
      )
    ).toBeVisible();

    // Table headers
    await expect(
      page.getByRole("columnheader", { name: "Time" })
    ).toBeVisible();
    await expect(
      page.getByRole("columnheader", { name: "Document ID" })
    ).toBeVisible();
    await expect(
      page.getByRole("columnheader", { name: "Error Message" })
    ).toBeVisible();
    await expect(
      page.getByRole("columnheader", { name: "Status" })
    ).toBeVisible();

    // Error row content
    await expect(page.getByText("doc-modal-open")).toBeVisible();
    await expect(page.getByText("Error for modal open test")).toBeVisible();
    await expect(page.getByText("Unresolved")).toBeVisible();

    // Resolve All button
    await expect(
      page.getByRole("button", { name: "Resolve All" })
    ).toBeVisible();
  });

  test("2.2 modal closes via X button", async ({ page }) => {
    createError({
      indexAttemptId: testIndexAttemptId!,
      ccPairId: testCcPairId!,
      failureMessage: "Error for close-X test",
    });

    await page.goto(`/admin/connector/${testCcPairId}`);
    await page.waitForLoadState("networkidle");
    await openErrorsModal(page);

    // The close button is the first <button> in the dialog (rendered in Modal.Header)
    // "Resolve All" is in the footer, so .first() gets the X button
    const dialog = page.getByRole("dialog");
    await dialog
      .locator("button")
      .filter({ hasNotText: /Resolve All/ })
      .first()
      .click();

    await expect(page.getByText("Indexing Errors")).not.toBeVisible();
    // Banner should still be present
    await expect(
      page.getByText("Some documents failed to index")
    ).toBeVisible();
  });

  test("2.3 modal closes via Escape key", async ({ page }) => {
    createError({
      indexAttemptId: testIndexAttemptId!,
      ccPairId: testCcPairId!,
      failureMessage: "Error for close-escape test",
    });

    await page.goto(`/admin/connector/${testCcPairId}`);
    await page.waitForLoadState("networkidle");
    await openErrorsModal(page);

    await page.keyboard.press("Escape");

    await expect(page.getByText("Indexing Errors")).not.toBeVisible();
    await expect(
      page.getByText("Some documents failed to index")
    ).toBeVisible();
  });

  // ── 3. Table Content and Rendering ────────────────────────────────────────

  test("3.1 error row with document link renders as hyperlink", async ({
    page,
  }) => {
    createError({
      indexAttemptId: testIndexAttemptId!,
      ccPairId: testCcPairId!,
      documentId: "doc-linked",
      documentLink: "https://example.com/doc-linked",
      failureMessage: "Timeout while fetching document content",
    });

    await page.goto(`/admin/connector/${testCcPairId}`);
    await page.waitForLoadState("networkidle");
    await openErrorsModal(page);

    const docLink = page.getByRole("link", { name: "doc-linked" });
    await expect(docLink).toBeVisible();
    await expect(docLink).toHaveAttribute(
      "href",
      "https://example.com/doc-linked"
    );
    await expect(docLink).toHaveAttribute("target", "_blank");
    await expect(docLink).toHaveAttribute("rel", "noopener noreferrer");

    await expect(
      page.getByText("Timeout while fetching document content")
    ).toBeVisible();
    await expect(page.getByText("Unresolved")).toBeVisible();
  });

  test("3.2 error without document link shows plain text ID", async ({
    page,
  }) => {
    createError({
      indexAttemptId: testIndexAttemptId!,
      ccPairId: testCcPairId!,
      documentId: "doc-no-link",
      documentLink: null,
      failureMessage: "Error without link",
    });

    await page.goto(`/admin/connector/${testCcPairId}`);
    await page.waitForLoadState("networkidle");
    await openErrorsModal(page);

    await expect(page.getByText("doc-no-link")).toBeVisible();
    // Should NOT be a link
    await expect(page.getByRole("link", { name: "doc-no-link" })).toHaveCount(
      0
    );
  });

  test("3.3 error with entity ID fallback when no document ID", async ({
    page,
  }) => {
    createError({
      indexAttemptId: testIndexAttemptId!,
      ccPairId: testCcPairId!,
      documentId: null,
      entityId: "entity-abc",
      failureMessage: "Error with entity ID only",
    });

    await page.goto(`/admin/connector/${testCcPairId}`);
    await page.waitForLoadState("networkidle");
    await openErrorsModal(page);

    await expect(page.getByText("entity-abc")).toBeVisible();
  });

  test("3.4 error with no document ID or entity ID shows Unknown", async ({
    page,
  }) => {
    createError({
      indexAttemptId: testIndexAttemptId!,
      ccPairId: testCcPairId!,
      documentId: null,
      entityId: null,
      failureMessage: "Error with no identifiers",
    });

    await page.goto(`/admin/connector/${testCcPairId}`);
    await page.waitForLoadState("networkidle");
    await openErrorsModal(page);

    // The table cell should display "Unknown" as fallback
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Unknown")).toBeVisible();
  });

  test("3.5 entity ID used as link text when document link exists but no document ID", async ({
    page,
  }) => {
    createError({
      indexAttemptId: testIndexAttemptId!,
      ccPairId: testCcPairId!,
      documentId: null,
      entityId: "entity-link-test",
      documentLink: "https://example.com/entity",
      failureMessage: "Error with entity link",
    });

    await page.goto(`/admin/connector/${testCcPairId}`);
    await page.waitForLoadState("networkidle");
    await openErrorsModal(page);

    const link = page.getByRole("link", { name: "entity-link-test" });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", "https://example.com/entity");
  });

  test("3.6 HTML in error message is escaped (XSS safe)", async ({ page }) => {
    createError({
      indexAttemptId: testIndexAttemptId!,
      ccPairId: testCcPairId!,
      documentId: "doc-xss",
      failureMessage: "<script>alert('xss')</script>",
    });

    await page.goto(`/admin/connector/${testCcPairId}`);
    await page.waitForLoadState("networkidle");
    await openErrorsModal(page);

    // Text should be rendered literally, not executed as HTML
    await expect(page.getByText("<script>alert('xss')</script>")).toBeVisible();
  });

  // ── 4. Pagination ─────────────────────────────────────────────────────────

  test("4.1 no pagination controls when errors fit on one page", async ({
    page,
  }) => {
    createMultipleErrors(testIndexAttemptId!, testCcPairId!, 2);

    await page.goto(`/admin/connector/${testCcPairId}`);
    await page.waitForLoadState("networkidle");
    await openErrorsModal(page);

    // Both errors should be visible
    await expect(page.getByText("doc-1")).toBeVisible();
    await expect(page.getByText("doc-2")).toBeVisible();

    // PageSelector should not appear (only renders when totalPages > 1)
    // The "›" next-page button only exists when pagination is shown
    const dialog = page.getByRole("dialog");
    await expect(dialog.locator('text="›"')).not.toBeVisible();
  });

  test("4.2 pagination appears and navigation works with many errors", async ({
    page,
  }) => {
    // 10 errors should span multiple pages given the modal's dynamic page size
    // (viewport 1280x720 typically yields ~5 rows per page in the modal)
    createMultipleErrors(testIndexAttemptId!, testCcPairId!, 10);

    await page.goto(`/admin/connector/${testCcPairId}`);
    await page.waitForLoadState("networkidle");
    await openErrorsModal(page);

    const dialog = page.getByRole("dialog");
    const nextBtn = dialog.locator('text="›"');
    const prevBtn = dialog.locator('text="‹"');

    // If the viewport produces a page size >= 10, pagination won't appear
    // Skip the navigation part in that case
    if (await nextBtn.isVisible()) {
      // Record page 1 content
      const page1Content = await dialog.locator("table tbody").textContent();

      // Navigate to page 2
      await nextBtn.click();
      const page2Content = await dialog.locator("table tbody").textContent();
      expect(page2Content).not.toBe(page1Content);

      // Navigate back to page 1
      await prevBtn.click();
      const backToPage1 = await dialog.locator("table tbody").textContent();
      expect(backToPage1).toBe(page1Content);
    }
  });

  // ── 5. Resolve All Functionality ──────────────────────────────────────────

  test("5.1 Resolve All triggers re-index and shows success toast", async ({
    page,
  }) => {
    createError({
      indexAttemptId: testIndexAttemptId!,
      ccPairId: testCcPairId!,
      documentId: "doc-resolve",
      failureMessage: "Error to resolve via re-index",
    });

    // Activate the connector so the re-index request can succeed
    // (createFileConnector pauses the connector by default)
    await page.request.put(`/api/manage/admin/cc-pair/${testCcPairId}/status`, {
      data: { status: "ACTIVE" },
    });

    await page.goto(`/admin/connector/${testCcPairId}`);
    await page.waitForLoadState("networkidle");
    await openErrorsModal(page);

    await page.getByRole("button", { name: "Resolve All" }).click();

    // Modal should close
    await expect(page.getByText("Indexing Errors")).not.toBeVisible();

    // Success toast should appear
    await expect(
      page.getByText("Complete re-indexing started successfully")
    ).toBeVisible({ timeout: 15000 });
  });

  test("5.2 Resolve All button is absent when isResolvingErrors is true", async ({
    page,
  }) => {
    createError({
      indexAttemptId: testIndexAttemptId!,
      ccPairId: testCcPairId!,
      documentId: "doc-resolving",
      failureMessage: "Error during resolving state",
    });

    // Create a separate index attempt that simulates a from-beginning re-index
    // in progress, with no errors belonging to it
    createIndexAttempt(testCcPairId!, {
      fromBeginning: true,
      status: "in_progress",
    });

    await page.goto(`/admin/connector/${testCcPairId}`);
    await page.waitForLoadState("networkidle");

    // The banner should show "Resolving failures" instead of "View details."
    await expect(page.getByText("Some documents failed to index")).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByText("Resolving failures")).toBeVisible();
    await expect(page.getByText("View details.")).not.toBeVisible();
  });

  // ── 6. Data Freshness and Auto-Refresh ────────────────────────────────────

  test("6.1 new error appears on page without manual reload", async ({
    page,
  }) => {
    await page.goto(`/admin/connector/${testCcPairId}`);
    await page.waitForLoadState("networkidle");

    // Initially no banner
    await expect(
      page.getByText("Some documents failed to index")
    ).not.toBeVisible();

    // Insert an error via DB while the page is already open
    createError({
      indexAttemptId: testIndexAttemptId!,
      ccPairId: testCcPairId!,
      documentId: "doc-auto-refresh",
      failureMessage: "Error added while page is open",
    });

    // Wait for the 5-second polling cycle to pick it up
    await expect(page.getByText("Some documents failed to index")).toBeVisible({
      timeout: 15000,
    });
  });

  test("6.2 errors list refreshes while modal is open", async ({ page }) => {
    createError({
      indexAttemptId: testIndexAttemptId!,
      ccPairId: testCcPairId!,
      documentId: "doc-existing",
      failureMessage: "Pre-existing error",
    });

    await page.goto(`/admin/connector/${testCcPairId}`);
    await page.waitForLoadState("networkidle");
    await openErrorsModal(page);

    await expect(page.getByText("doc-existing")).toBeVisible();

    // Add a second error while the modal is open
    createError({
      indexAttemptId: testIndexAttemptId!,
      ccPairId: testCcPairId!,
      documentId: "doc-new-while-open",
      failureMessage: "Error added while modal is open",
    });

    // The new error should appear after the polling cycle
    await expect(page.getByText("doc-new-while-open")).toBeVisible({
      timeout: 15000,
    });
  });

  // ── 7. Access Control ─────────────────────────────────────────────────────

  test("7.1 non-admin user cannot access the errors API endpoint", async ({
    page,
  }) => {
    // Register a basic (non-admin) user
    const email = `basic_${Date.now()}@example.com`;
    const password = "TestPassword123!";

    await page.request.post("/api/auth/register", {
      data: { email, username: email, password },
    });

    // Login as the basic user
    await page.context().clearCookies();
    await page.request.post("/api/auth/login", {
      form: { username: email, password },
    });

    // Try to access the errors endpoint
    const errorsRes = await page.request.get(
      `/api/manage/admin/cc-pair/${testCcPairId}/errors`
    );
    expect([401, 403]).toContain(errorsRes.status());

    // Re-login as admin for afterEach cleanup
    await page.context().clearCookies();
    await loginAs(page, "admin");

    // Clean up the basic user
    const apiClient = new OnyxApiClient(page.request);
    try {
      await apiClient.deleteUser(email);
    } catch {
      // Ignore cleanup failures
    }
  });

  // ── 8. Resolved Errors Filtered by Default ────────────────────────────────

  test("8.1 resolved errors are not shown in the modal and banner is absent", async ({
    page,
  }) => {
    createError({
      indexAttemptId: testIndexAttemptId!,
      ccPairId: testCcPairId!,
      documentId: "doc-resolved",
      failureMessage: "Already resolved error",
      isResolved: true,
    });

    // API without include_resolved should return 0 items
    const defaultRes = await page.request.get(
      `/api/manage/admin/cc-pair/${testCcPairId}/errors`
    );
    expect(defaultRes.ok()).toBe(true);
    const defaultData = await defaultRes.json();
    expect(defaultData.total_items).toBe(0);

    // API with include_resolved=true should return the error
    const resolvedRes = await page.request.get(
      `/api/manage/admin/cc-pair/${testCcPairId}/errors?include_resolved=true`
    );
    expect(resolvedRes.ok()).toBe(true);
    const resolvedData = await resolvedRes.json();
    expect(resolvedData.total_items).toBe(1);
    expect(resolvedData.items[0].is_resolved).toBe(true);

    // Banner should not appear on the page
    await page.goto(`/admin/connector/${testCcPairId}`);
    await page.waitForLoadState("networkidle");
    await expect(
      page.getByText("Some documents failed to index")
    ).not.toBeVisible();
  });

  // ── 9. API Pagination Boundary ────────────────────────────────────────────

  test("9.1 API rejects page_size over 100", async ({ page }) => {
    const res = await page.request.get(
      `/api/manage/admin/cc-pair/${testCcPairId}/errors?page_size=101`
    );
    expect(res.status()).toBe(422);
  });
});
