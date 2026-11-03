/** The connector page's layout and tab edges: the panel's beside sizing, the chart span across tabs, an indexed pair without current attempts, a first group sync, the hidden chart card, its return on a failed poll and the top bar. */
import { Suspense } from "react";
import {
  act,
  cleanup,
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import ConnectorDetailPage from "@/views/admin/connectors/ConnectorDetailPage";
import { AdminTopBarSlotContext } from "@/layouts/chromes/AdminTopBarSlot";
import {
  ConnectorCredentialPairStatus,
  type CCPairFullInfo,
  type CCPairRun,
  type CCPairThroughputResponse,
} from "@/lib/connectors/types";
import { THROUGHPUT_POLL_MS } from "@/lib/connectors/hooks";
import type {
  SliceRange,
  ThroughputChartViewProps,
} from "@/views/admin/connectors/ConnectorDetailPage/ThroughputChart";
import {
  installChartLayout,
  resetChartLayout,
} from "@tests/setup/throughputChartTestUtils";

let mockQuery = new URLSearchParams();
jest.mock("next/navigation", () => ({
  ...jest.requireActual("next/navigation"),
  useRouter: () => ({
    push: jest.fn(),
    replace: jest.fn(),
    prefetch: jest.fn(),
    back: jest.fn(),
    refresh: jest.fn(),
  }),
  useSearchParams: () => mockQuery,
  usePathname: () => "/admin/connector/7",
}));

const SPAN: SliceRange = {
  since: "2026-11-02T10:00:00.000Z",
  until: "2026-11-02T11:00:00.000Z",
};

// A button beside the real chart stands in for a drag across the bars.
jest.mock(
  "@/views/admin/connectors/ConnectorDetailPage/ThroughputChart",
  () => {
    const actual = jest.requireActual(
      "@/views/admin/connectors/ConnectorDetailPage/ThroughputChart"
    );
    const { Button } = jest.requireActual("@opal/components");
    return {
      ...actual,
      __esModule: true,
      ThroughputChartView: (props: ThroughputChartViewProps) => (
        <>
          <actual.ThroughputChartView {...props} />
          <Button onClick={() => props.onRangeSelect?.(SPAN)}>pick span</Button>
        </>
      ),
    };
  }
);

const CC_PAIR_ID = 7;
const NOW = Date.now();
const HOUR_MS = 3_600_000;

/** An active public Confluence pair that has indexed before. */
function ccPair(overrides: Partial<CCPairFullInfo> = {}): CCPairFullInfo {
  const created = new Date(NOW - 90 * 24 * HOUR_MS).toISOString();
  return {
    id: CC_PAIR_ID,
    name: "Policy knowledge",
    status: ConnectorCredentialPairStatus.ACTIVE,
    in_repeated_error_state: false,
    num_docs_indexed: 3248,
    connector: {
      id: 11,
      name: "Policy knowledge",
      source: "confluence",
      input_type: "poll",
      connector_specific_config: {},
      refresh_freq: 1800,
      prune_freq: 86400,
      check_freq: null,
      indexing_start: null,
      access_type: "public",
      credential_ids: [12],
      time_created: created,
      time_updated: created,
    },
    credential: {
      id: 12,
      credential_json: {},
      admin_public: true,
      source: "confluence",
      name: "Confluence account",
      user_id: null,
      user_email: null,
      user_personal_name: null,
      time_created: created,
      time_updated: created,
    },
    number_of_index_attempts: 15,
    last_index_attempt_status: "success",
    latest_deletion_attempt: null,
    access_type: "public",
    is_editable_for_current_user: true,
    permissions: { operate: true, edit: true, delete: true },
    deletion_failure_message: null,
    indexing: false,
    creator: null,
    creator_email: null,
    last_indexed: new Date(NOW - HOUR_MS).toISOString(),
    last_pruned: null,
    last_full_permission_sync: null,
    last_time_perm_sync: null,
    last_time_external_group_sync: null,
    overall_indexing_speed: null,
    latest_checkpoint_description: null,
    last_permission_sync_attempt_status: null,
    permission_syncing: false,
    last_permission_sync_attempt_finished: null,
    last_permission_sync_attempt_error_message: null,
    supports_doc_permission_sync: false,
    supports_targeted_reindex: true,
    pending_backfills: [],
    has_named_checks: false,
    indexing_hold: null,
    ...overrides,
  } as CCPairFullInfo;
}

function throughput(withData: boolean): CCPairThroughputResponse {
  return {
    window_start: new Date(NOW - 24 * HOUR_MS).toISOString(),
    window_end: new Date(NOW).toISOString(),
    docs_indexed: Array.from({ length: 24 }, (_, index) =>
      withData && index === 3 ? 40 : 0
    ),
    runs: [],
  };
}

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

// The chart fetches once its width is measured, which jsdom never lays out.
beforeEach(() => installChartLayout(600));

const realFetch = global.fetch;
afterEach(() => {
  resetChartLayout();
  global.fetch = realFetch;
  mockQuery = new URLSearchParams();
  window.history.replaceState(null, "", "/");
});

/** A failed index attempt, which both the runs card and the panel's failures list. */
function failedIndexRun(id: number): CCPairRun {
  const started = new Date(NOW - HOUR_MS).toISOString();
  return {
    kind: "indexing",
    time_created: started,
    resolved_at: null,
    superseded: false,
    is_retry: false,
    attempt: {
      id,
      status: "failed",
      from_beginning: false,
      new_docs_indexed: 0,
      docs_removed_from_index: 0,
      total_docs_indexed: 0,
      error_msg: "Connector failed",
      error_count: 0,
      open_error_count: 0,
      open_doc_error_count: 0,
      full_exception_trace: null,
      time_started: started,
      time_updated: started,
      time_finished: started,
      is_new_model: false,
      is_backfill: false,
    },
  } as CCPairRun;
}

/** Serves the pair, a runs feed with `groupSyncRuns` group syncs and `runs` for every other query, its throughput and no attempts. Anything else stays pending. */
function stubApi(
  pair: CCPairFullInfo,
  chartData: boolean,
  groupSyncRuns: number,
  runs: CCPairRun[]
) {
  global.fetch = jest.fn((input: RequestInfo | URL) => {
    const path = new URL(String(input), "http://localhost").pathname;
    const base = `/api/manage/admin/cc-pair/${CC_PAIR_ID}`;
    if (path === base) return Promise.resolve(jsonResponse(pair));
    if (path === `${base}/runs`) {
      const groupSyncs = new URL(
        String(input),
        "http://localhost"
      ).searchParams.has("kinds", "group_sync");
      return Promise.resolve(
        jsonResponse({
          items: groupSyncs ? [] : runs,
          total_items: groupSyncs ? groupSyncRuns : runs.length,
          kinds: ["indexing"],
          status_counts: { running: 0, succeeded: 0, failed: 0, canceled: 0 },
        })
      );
    }
    if (path === `${base}/throughput`) {
      return Promise.resolve(jsonResponse(throughput(chartData)));
    }
    if (path === `${base}/index-attempts`) {
      return Promise.resolve(
        jsonResponse({ items: [], total_items: 0, page_num: 0, page_size: 1 })
      );
    }
    return new Promise<Response>(() => {});
  }) as typeof fetch;
}

interface Setup {
  pair?: CCPairFullInfo;
  chartData?: boolean;
  query?: string;
  /** Group sync runs the feed counts, in any state. */
  groupSyncRuns?: number;
  /** Every other runs query lists these. */
  runs?: CCPairRun[];
  /** The admin top bar's element, as AdminChrome provides it on a narrow screen. */
  topBar?: HTMLElement | null;
}

async function renderPage({
  pair = ccPair(),
  chartData = true,
  query = "",
  groupSyncRuns = 0,
  runs = [],
  topBar = null,
}: Setup = {}) {
  mockQuery = new URLSearchParams(query);
  window.history.replaceState(
    null,
    "",
    `/admin/connector/${CC_PAIR_ID}${query ? `?${query}` : ""}`
  );
  stubApi(pair, chartData, groupSyncRuns, runs);
  const params = Promise.resolve({ ccPairId: String(CC_PAIR_ID) });
  await act(async () => {
    render(
      <AdminTopBarSlotContext.Provider value={topBar}>
        <Suspense fallback={null}>
          <ConnectorDetailPage params={params} />
        </Suspense>
      </AdminTopBarSlotContext.Provider>
    );
  });
  await screen.findAllByText("Policy knowledge");
}

function indexingTab(): HTMLElement {
  return screen.getByRole("tab", { name: "Indexing" });
}

function panelOf(tab: HTMLElement): HTMLElement {
  return document.getElementById(
    tab.getAttribute("aria-controls") as string
  ) as HTMLElement;
}

/** The runs feed requests so far, as their query strings. */
function runsQueries(): string[] {
  return jest
    .mocked(global.fetch)
    .mock.calls.map(([input]) => new URL(String(input), "http://localhost"))
    .filter((url) => url.pathname.endsWith(`/cc-pair/${CC_PAIR_ID}/runs`))
    .map((url) => url.search);
}

describe("connector page layout edges", () => {
  it("sizes the Activities panel beside the column by the body's container, not the viewport", async () => {
    await renderPage();
    const classes = Array.from(
      screen.getByTestId("connector-activity").classList
    );
    expect(classes).toContain("@min-[51rem]:w-100");
    expect(classes).toContain("@min-[51rem]:contain-size");
    expect(classes.filter((name) => name.startsWith("lg:"))).toEqual([]);
  });

  it("drops the chart span when the admin leaves the Indexing tab, so the panel stops filtering by it", async () => {
    const user = setupUser();
    await renderPage({ query: "tab=indexing" });
    await waitFor(() =>
      expect(indexingTab()).toHaveAttribute("aria-selected", "true")
    );
    await user.click(
      await within(panelOf(indexingTab())).findByRole("button", {
        name: "pick span",
      })
    );
    const spanSince = `since=${encodeURIComponent(SPAN.since)}`;
    await waitFor(() =>
      expect(runsQueries().some((query) => query.includes(spanSince))).toBe(
        true
      )
    );

    await user.click(
      screen.getByRole("tab", { name: "Connector Configurations" })
    );
    // The panel's feed refetches without the span.
    const before = runsQueries().length;
    await waitFor(() => expect(runsQueries().length).toBeGreaterThan(before));
    expect(
      runsQueries()
        .slice(before)
        .some((query) => query.includes(spanSince))
    ).toBe(false);
  });

  it("treats a pair with documents but no attempt under the current model as indexed", async () => {
    await renderPage({
      pair: ccPair({
        number_of_index_attempts: 0,
        last_index_attempt_status: null,
        last_indexed: null,
      }),
    });
    expect(indexingTab()).toBeEnabled();
    const user = setupUser();
    await user.click(screen.getByRole("button", { name: "Manage Index" }));
    const items = (await screen.findAllByRole("menuitem")).map(
      (item) => item.textContent ?? ""
    );
    expect(items.some((text) => text.includes("Update Index"))).toBe(true);
    expect(items.some((text) => text.includes("Full Re-index"))).toBe(true);
  });

  it("opens the Indexing tab for a first group sync that has not succeeded yet", async () => {
    const neverIndexed = {
      number_of_index_attempts: 0,
      num_docs_indexed: 0,
      last_index_attempt_status: null,
      last_indexed: null,
      access_type: "sync",
    } as const;
    await renderPage({ pair: ccPair(neverIndexed) });
    expect(indexingTab()).toBeDisabled();
    cleanup();

    await renderPage({ pair: ccPair(neverIndexed), groupSyncRuns: 1 });
    await waitFor(() => expect(indexingTab()).toBeEnabled());
  });

  it("leaves nothing above Indexing Runs while the chart card is hidden", async () => {
    await renderPage({ query: "tab=indexing", chartData: false });
    await waitFor(() =>
      expect(indexingTab()).toHaveAttribute("aria-selected", "true")
    );
    const panel = panelOf(indexingTab());
    const heading = await within(panel).findByText("Indexing Runs");
    await waitFor(() =>
      expect(
        jest
          .mocked(global.fetch)
          .mock.calls.some(([input]) => String(input).includes("/throughput"))
      ).toBe(true)
    );
    await waitFor(() => {
      const stack = panel.firstElementChild as HTMLElement;
      expect(stack.children).toHaveLength(1);
      expect(stack.firstElementChild).toContainElement(heading);
    });
  });

  it("brings the chart card back with its error when a poll fails after an empty window", async () => {
    // Fake from the start so the chart's poll timer is one the test can run.
    jest.useFakeTimers({ advanceTimers: true });
    try {
      await renderPage({ query: "tab=indexing", chartData: false });
      const panel = panelOf(indexingTab());
      await within(panel).findByText("Indexing Runs");
      await waitFor(() =>
        expect(
          jest
            .mocked(global.fetch)
            .mock.calls.some(([input]) => String(input).includes("/throughput"))
        ).toBe(true)
      );
      expect(within(panel).queryByText("Document Indexing")).toBeNull();

      const served = jest.mocked(global.fetch).getMockImplementation()!;
      global.fetch = jest.fn((input: RequestInfo | URL) =>
        String(input).includes("/throughput")
          ? Promise.resolve({
              ok: false,
              status: 500,
              json: async () => ({ detail: "boom" }),
              text: async () => "boom",
            } as unknown as Response)
          : served(input)
      ) as typeof fetch;
      await act(async () => {
        jest.advanceTimersByTime(THROUGHPUT_POLL_MS);
      });
      expect(
        await within(panel).findByText("Document Indexing")
      ).toBeInTheDocument();
    } finally {
      jest.useRealTimers();
    }
  });

  it("lifts an index run's line while its activity card is hovered", async () => {
    const run = failedIndexRun(41);
    const user = setupUser();
    await renderPage({ query: "tab=indexing", runs: [run] });
    const line = await within(panelOf(indexingTab())).findByTestId("run-row");
    const card = (
      await within(screen.getByTestId("connector-activity")).findAllByTestId(
        "activity-card"
      )
    )[0]!;
    expect(line).toHaveAttribute("data-shadow", "none");

    await user.hover(card);
    await waitFor(() =>
      expect(line).not.toHaveAttribute("data-shadow", "none")
    );
    await user.unhover(card);
    await waitFor(() => expect(line).toHaveAttribute("data-shadow", "none"));
  });

  it("puts the back link in the admin top bar while there is one", async () => {
    const topBar = document.createElement("div");
    document.body.appendChild(topBar);
    await renderPage({ topBar });
    expect(
      within(topBar).getByRole("link", { name: /All Connectors/ })
    ).toBeInTheDocument();
    topBar.remove();
  });
});
