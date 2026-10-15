/** The run list and the activity panel: a file connector shows no run-type
 * filter and no activity, a perm-synced pair's failed syncs open their
 * error and the doc sync's shows in the panel, and the status card's window
 * and the count tags filter the list. */

import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";

import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { AdminConnectorDetailPage } from "@tests/e2e/pages/AdminConnectorDetailPage";

const MOCK_SYNC_CC_PAIR_ID = 99999;
const MOCK_SOURCE = "google_drive";
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

/** The `CCPairFullInfo` fields the page reads, for a perm-synced pair. */
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
      check_freq: null,
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
      user_email: null,
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
    pending_backfills: [],
    has_named_checks: false,
    indexing_hold: null,
  };
}

/** A failed doc sync and a failed group sync, newest first, as `/runs` returns them. */
function failedSyncRuns() {
  return {
    items: [
      {
        kind: "doc_permission_sync",
        time_created: "2026-05-03T12:05:00Z",
        attempt: {
          id: 5001,
          status: "failed",
          error_message: MOCK_DOC_ERROR_MESSAGE,
          full_exception_trace: null,
          total_docs_synced: 0,
          docs_with_permission_errors: 0,
          time_created: "2026-05-03T12:05:00Z",
          time_started: "2026-05-03T12:05:10Z",
          time_finished: "2026-05-03T12:06:30Z",
        },
      },
      {
        kind: "group_sync",
        time_created: "2026-05-03T12:00:00Z",
        attempt: {
          id: 6001,
          status: "failed",
          error_message: MOCK_GROUP_ERROR_MESSAGE,
          full_exception_trace: null,
          total_users_processed: 0,
          total_groups_processed: 0,
          total_group_memberships_synced: 0,
          time_created: "2026-05-03T12:00:00Z",
          time_started: "2026-05-03T12:00:10Z",
          time_finished: "2026-05-03T12:01:30Z",
        },
      },
    ],
    total_items: 2,
    kinds: ["indexing", "doc_permission_sync", "group_sync"],
    status_counts: { running: 0, succeeded: 0, failed: 2, canceled: 0 },
  };
}

/** Mocks the page's fetches for `MOCK_SYNC_CC_PAIR_ID`. Other requests reach the real backend. */
async function mockSyncConnector(page: Page): Promise<void> {
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
  await page.route(`${base}/throughput*`, async (route) => {
    await route.fulfill(
      jsonResponse({
        window_start: new Date(Date.now() - 3_600_000).toISOString(),
        window_end: new Date().toISOString(),
        docs_indexed: [0, 0, 0],
        runs: [],
      })
    );
  });
  await page.route(`${base}/errors*`, async (route) => {
    await route.fulfill(jsonResponse({ items: [], total_items: 0 }));
  });
  // The feed holds failed syncs only, so a query for runs with document errors finds none.
  await page.route(`${base}/runs*`, async (route) => {
    const params = new URL(route.request().url()).searchParams;
    const failedOnly = !params.has("errors");
    await route.fulfill(
      jsonResponse(
        failedOnly
          ? failedSyncRuns()
          : { ...failedSyncRuns(), items: [], total_items: 0 }
      )
    );
  });
}

test.describe("Connector runs", () => {
  test("a file connector shows no run-type filter and no activity", async ({
    page,
  }) => {
    const apiClient = new OnyxApiClient(page.request);
    const ccPairId = await apiClient.createFileConnector(
      `E2E Runs File ${Date.now()}`
    );
    try {
      const detail = new AdminConnectorDetailPage(page);
      await detail.goto(ccPairId);
      await detail.expectNoRuns();
      await detail.expectNoActivity();
      await expect(detail.runKindFilter).toHaveCount(0);
    } finally {
      await apiClient.deleteCCPair(ccPairId);
    }
  });

  test("a failed sync run opens its error", async ({ page }) => {
    await mockSyncConnector(page);
    const detail = new AdminConnectorDetailPage(page);
    await detail.goto(MOCK_SYNC_CC_PAIR_ID);
    await detail.expectRunsVisible();
    await expect(detail.runKindFilter).toBeVisible();
    await detail.expectActivityShows(MOCK_DOC_ERROR_MESSAGE);
    await detail.expectActivityGroups(["2 Failures"]);

    const docModal = await detail.openRunLogs(
      0,
      "Document Permission Sync Error"
    );
    // CodePreview splits the text into spans, so match the dialog's text, not one node.
    await expect(docModal).toContainText(MOCK_DOC_ERROR_MESSAGE);
    await detail.closeRunLogs(docModal);

    const groupModal = await detail.openRunLogs(
      1,
      "Group Membership Sync Error"
    );
    await expect(groupModal).toContainText(MOCK_GROUP_ERROR_MESSAGE);
  });

  test("the status card's window and the count tags filter the runs", async ({
    page,
  }) => {
    await mockSyncConnector(page);
    const runsQueries: URLSearchParams[] = [];
    const chartWindows: string[] = [];
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (url.pathname.endsWith(`/cc-pair/${MOCK_SYNC_CC_PAIR_ID}/runs`)) {
        runsQueries.push(url.searchParams);
      }
      if (
        url.pathname.endsWith(`/cc-pair/${MOCK_SYNC_CC_PAIR_ID}/throughput`)
      ) {
        chartWindows.push(url.searchParams.get("window") ?? "");
      }
    });
    const detail = new AdminConnectorDetailPage(page);
    await detail.goto(MOCK_SYNC_CC_PAIR_ID);
    await detail.expectRunsVisible();

    // All time lists every run and shows the chart's widest window.
    await expect(detail.timeWindowPicker).toHaveText("All time");
    await expect.poll(() => chartWindows.at(-1)).toBe("7d");
    expect(runsQueries.every((query) => !query.has("since"))).toBe(true);

    await detail.pickTimeWindow("Last 24 hours");
    await expect.poll(() => chartWindows.at(-1)).toBe("24h");
    await expect
      .poll(() => runsQueries.at(-1)?.has("since") ?? false)
      .toBe(true);

    const failed = detail.countTag("2 runs failed");
    await expect(failed).toHaveAttribute("aria-pressed", "false");
    await failed.click();
    await expect(failed).toHaveAttribute("aria-pressed", "true");
    await expect
      .poll(() => runsQueries.at(-1)?.getAll("status_groups"))
      .toEqual(["failed"]);

    await failed.click();
    await expect(failed).toHaveAttribute("aria-pressed", "false");
    await expect
      .poll(() => runsQueries.at(-1)?.getAll("status_groups"))
      .toEqual([]);
  });
});
