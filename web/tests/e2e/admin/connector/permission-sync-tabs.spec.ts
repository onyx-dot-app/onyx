/**
 * E2E coverage for the connector-detail "Advanced" → permission-sync tabs UX.
 *
 * Three scenarios:
 *
 * 1. **Non-sync connector** (real file cc-pair): the legacy "Indexing
 *    Attempts" title + table render exactly as before. No tab UI.
 * 2. **Sync connector** (route-mocked, since spinning up a real
 *    permission-synced cc-pair would require source-specific OAuth /
 *    credentials we don't have in CI): all three tabs render, the
 *    Document Permissions tab loads its endpoint and shows the row, and
 *    the Group Membership tab shows the explicit "not applicable"
 *    message rather than a blank empty state.
 * 3. **Failed-attempt error modal**: in both sync tables, a `failed` row
 *    surfaces the error message as a clickable button that opens
 *    `ExceptionTraceModal` with a tab-specific title and the full error
 *    text rendered in the body.
 *
 * The backend behavior (route correctness, `applicable` flag computation,
 * source-wide attribution for cc-pair-agnostic sources) is covered by
 * the external-dependency-unit suite at
 * `backend/tests/external_dependency_unit/permission_sync/test_cc_pair_sync_attempts_routes.py`,
 * landed in PR A. This spec deliberately scopes itself to the frontend
 * rendering decisions PR B–D introduce.
 */

import { test, expect } from "@playwright/test";
import type { Page, Route } from "@playwright/test";

import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

const MOCK_SYNC_CC_PAIR_ID = 99999;
const MOCK_SOURCE = "google_drive";
const MOCK_DOC_ATTEMPT_ID = 5001;
const MOCK_GROUP_ATTEMPT_ID = 6001;
const MOCK_DOC_ERROR_MESSAGE =
  "Traceback: doc permission sync failed because the upstream API returned 503";
const MOCK_GROUP_ERROR_MESSAGE =
  "Traceback: group membership sync failed because the upstream API returned 502";

function jsonResponse(data: unknown, status = 200) {
  return {
    status,
    contentType: "application/json",
    body: JSON.stringify(data),
  };
}

/**
 * Minimal `CCPairFullInfo` shape needed for the page to render with
 * `access_type === "sync"`. Fields not exercised by the assertions are
 * filled with neutral defaults.
 */
function syncCCPairFixture() {
  const now = new Date().toISOString();
  return {
    id: MOCK_SYNC_CC_PAIR_ID,
    name: "Mock Sync Connector",
    status: "ACTIVE",
    in_repeated_error_state: false,
    num_docs_indexed: 0,
    connector: {
      id: 12345,
      name: "Mock Sync Connector",
      source: MOCK_SOURCE,
      input_type: "poll",
      connector_specific_config: {},
      refresh_freq: 600,
      prune_freq: null,
      indexing_start: null,
      access_type: "sync",
      credential_ids: [54321],
      time_created: now,
      time_updated: now,
    },
    credential: {
      id: 54321,
      name: "Mock Credential",
      credential_json: {},
      admin_public: true,
      time_created: now,
      time_updated: now,
      source: MOCK_SOURCE,
      user_id: null,
      curator_public: true,
    },
    number_of_index_attempts: 0,
    last_index_attempt_status: null,
    latest_deletion_attempt: null,
    access_type: "sync",
    is_editable_for_current_user: true,
    deletion_failure_message: null,
    indexing: false,
    creator: null,
    creator_email: null,
    last_indexed: null,
    last_pruned: null,
    last_full_permission_sync: null,
    overall_indexing_speed: null,
    latest_checkpoint_description: null,
    last_permission_sync_attempt_status: null,
    permission_syncing: false,
    last_permission_sync_attempt_finished: null,
    last_permission_sync_attempt_error_message: null,
  };
}

interface SyncMockOptions {
  /** Doc-permission attempts response. Must mirror `CCPairSyncAttemptsResponse`. */
  docPermissions: {
    applicable: boolean;
    items: Array<Record<string, unknown>>;
    total_items: number;
  };
  /** Group-membership attempts response. */
  externalGroup: {
    applicable: boolean;
    items: Array<Record<string, unknown>>;
    total_items: number;
  };
}

/**
 * Wires up route mocks for everything the connector-detail page fetches
 * for `MOCK_SYNC_CC_PAIR_ID`. Other endpoints (auth, license, llm
 * providers, etc.) are left untouched and hit the real backend.
 *
 * Routes are registered parent-first; Playwright runs them LIFO, so a
 * request to `/cc-pair/99999/index-attempts?...` is handled by the
 * `index-attempts` route, not the bare `/cc-pair/99999` route.
 */
async function mockSyncConnectorEndpoints(
  page: Page,
  { docPermissions, externalGroup }: SyncMockOptions
): Promise<void> {
  const base = `**/api/manage/admin/cc-pair/${MOCK_SYNC_CC_PAIR_ID}`;

  await page.route(base, async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill(jsonResponse(syncCCPairFixture()));
      return;
    }
    await route.continue();
  });

  await page.route(`${base}/index-attempts*`, async (route) => {
    await route.fulfill(jsonResponse({ items: [], total_items: 0 }));
  });

  await page.route(`${base}/errors*`, async (route) => {
    await route.fulfill(jsonResponse({ items: [], total_items: 0 }));
  });

  await page.route(
    `${base}/permission-sync-attempts*`,
    async (route: Route) => {
      await route.fulfill(jsonResponse(docPermissions));
    }
  );

  await page.route(
    `${base}/external-group-sync-attempts*`,
    async (route: Route) => {
      await route.fulfill(jsonResponse(externalGroup));
    }
  );
}

test.describe("Permission sync tabs", () => {
  test("non-sync connector: renders legacy Indexing Attempts table, no tabs", async ({
    page,
  }) => {
    const apiClient = new OnyxApiClient(page.request);
    const ccPairId = await apiClient.createFileConnector(
      `E2E PermSyncTabs NonSync ${Date.now()}`
    );

    try {
      await page.goto(`/admin/connector/${ccPairId}`);
      await page.waitForLoadState("networkidle");

      await page.getByRole("button", { name: "Advanced" }).click();

      await expect(
        page.getByRole("heading", { name: "Indexing Attempts" })
      ).toBeVisible();

      // No tab triggers should appear for a non-sync (file) connector.
      await expect(page.getByRole("tab", { name: "Indexing" })).toHaveCount(0);
      await expect(
        page.getByRole("tab", { name: "Document Permission Sync" })
      ).toHaveCount(0);
      await expect(
        page.getByRole("tab", { name: "Group Membership Sync" })
      ).toHaveCount(0);
    } finally {
      await apiClient.deleteCCPair(ccPairId);
    }
  });

  test("sync connector: renders all three tabs, doc tab shows rows, group tab shows not-applicable message", async ({
    page,
  }) => {
    await mockSyncConnectorEndpoints(page, {
      docPermissions: {
        applicable: true,
        items: [
          {
            id: MOCK_DOC_ATTEMPT_ID,
            status: "success",
            error_message: null,
            total_docs_synced: 42,
            docs_with_permission_errors: 0,
            time_created: "2026-05-03T11:55:00Z",
            time_started: "2026-05-03T12:00:00Z",
            time_finished: "2026-05-03T12:01:30Z",
          },
        ],
        total_items: 1,
      },
      externalGroup: {
        applicable: false,
        items: [],
        total_items: 0,
      },
    });

    await page.goto(`/admin/connector/${MOCK_SYNC_CC_PAIR_ID}`);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Advanced" }).click();

    const indexingTab = page.getByRole("tab", { name: "Indexing" });
    const docPermissionsTab = page.getByRole("tab", {
      name: "Document Permission Sync",
    });
    const groupMembershipTab = page.getByRole("tab", {
      name: "Group Membership Sync",
    });

    await expect(indexingTab).toBeVisible();
    await expect(docPermissionsTab).toBeVisible();
    await expect(groupMembershipTab).toBeVisible();
    // Indexing is the default — the legacy "Indexing Attempts" header
    // does NOT render inside the tabbed flow; the tab triggers are the
    // visual header now.
    await expect(indexingTab).toHaveAttribute("data-state", "active");

    await docPermissionsTab.click();
    await expect(docPermissionsTab).toHaveAttribute("data-state", "active");
    // The DocPermissionSyncAttemptsTable renders column headers when
    // attempts.length > 0; the "Docs Synced" header is a stable signal
    // that the table (not the empty/not-applicable card) is showing.
    await expect(
      page.getByRole("columnheader", { name: "Docs Synced" })
    ).toBeVisible();
    await expect(
      page.getByText("No document permission sync attempts yet")
    ).toHaveCount(0);

    await groupMembershipTab.click();
    await expect(groupMembershipTab).toHaveAttribute("data-state", "active");
    // The explicit not-applicable message — distinct from the empty
    // "no attempts scheduled yet" state on a fresh applicable tab.
    await expect(
      page.getByText(
        "This connector does not use a separate group-membership syncing job."
      )
    ).toBeVisible();
    // And the table headers from DocPermissions should NOT bleed through —
    // Radix's default Tabs.Content unmount confirms tabs are independent.
    await expect(
      page.getByRole("columnheader", { name: "Docs Synced" })
    ).toHaveCount(0);
  });

  test("sync connector: clicking a failed row's Error Message opens the trace modal in both sync tables", async ({
    page,
  }) => {
    await mockSyncConnectorEndpoints(page, {
      docPermissions: {
        applicable: true,
        items: [
          {
            id: MOCK_DOC_ATTEMPT_ID,
            status: "failed",
            error_message: MOCK_DOC_ERROR_MESSAGE,
            total_docs_synced: 0,
            docs_with_permission_errors: 0,
            time_created: "2026-05-03T11:55:00Z",
            time_started: "2026-05-03T12:00:00Z",
            time_finished: "2026-05-03T12:01:30Z",
          },
        ],
        total_items: 1,
      },
      externalGroup: {
        applicable: true,
        items: [
          {
            id: MOCK_GROUP_ATTEMPT_ID,
            status: "failed",
            error_message: MOCK_GROUP_ERROR_MESSAGE,
            total_users_processed: 0,
            total_groups_processed: 0,
            total_group_memberships_synced: 0,
            time_created: "2026-05-03T11:55:00Z",
            time_started: "2026-05-03T12:00:00Z",
            time_finished: "2026-05-03T12:01:30Z",
          },
        ],
        total_items: 1,
      },
    });

    await page.goto(`/admin/connector/${MOCK_SYNC_CC_PAIR_ID}`);
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "Advanced" }).click();

    await page.getByRole("tab", { name: "Document Permission Sync" }).click();
    // The error-message button is keyed on the cell's aria-label so the
    // assertion stays robust if the truncated text changes.
    await page.getByRole("button", { name: "View full error message" }).click();

    const docModal = page.getByRole("dialog", {
      name: "Document Permission Sync Error",
    });
    await expect(docModal).toBeVisible();
    // `toContainText` concatenates text across descendants — needed
    // because `CodePreview` runs the body through a syntax highlighter
    // that splits each token into its own `<span>`.
    await expect(docModal).toContainText(MOCK_DOC_ERROR_MESSAGE);

    // Escape closes Radix dialogs; the listener restores focus to the
    // trigger so re-entering the tab does not race with state cleanup.
    await page.keyboard.press("Escape");
    await expect(docModal).not.toBeVisible();

    await page.getByRole("tab", { name: "Group Membership Sync" }).click();
    await page.getByRole("button", { name: "View full error message" }).click();

    const groupModal = page.getByRole("dialog", {
      name: "Group Membership Sync Error",
    });
    await expect(groupModal).toBeVisible();
    await expect(groupModal).toContainText(MOCK_GROUP_ERROR_MESSAGE);
  });
});
