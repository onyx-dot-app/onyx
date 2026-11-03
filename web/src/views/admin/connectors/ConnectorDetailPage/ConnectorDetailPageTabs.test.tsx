/** The connector page: two tabs, the Indexing tab's cards, the Manage Index menu by state, the one-column layout below 816 px, and the layout and tab edges (panel sizing, chart span across tabs, first syncs, the hidden chart card, the top bar). */
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
import { SvgLongWait } from "@opal/illustrations";
import {
  ConnectorCredentialPairStatus,
  type CCPairFullInfo,
  type CCPairRun,
  type CCPairRunsResponse,
  type CCPairThroughputResponse,
} from "@/lib/connectors/types";
import { THROUGHPUT_POLL_MS } from "@/lib/connectors/hooks";
import type {
  SliceRange,
  ThroughputChartViewProps,
} from "@/views/admin/connectors/ConnectorDetailPage/ThroughputChart";
import englishMessages from "@/i18n/messages/en.json";
import {
  installChartLayout,
  resetChartLayout,
} from "@tests/setup/throughputChartTestUtils";

const mockPush = jest.fn();
const mockReplace = jest.fn();
const mockRouter = {
  push: mockPush,
  replace: mockReplace,
  prefetch: jest.fn(),
  back: jest.fn(),
  refresh: jest.fn(),
};
let mockQuery = new URLSearchParams();
jest.mock("next/navigation", () => ({
  ...jest.requireActual("next/navigation"),
  useRouter: () => mockRouter,
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
const MINUTE_MS = 60_000;

/** The English message at `path`. A missing key fails the test. */
function copy(path: string): string {
  const raw = path
    .split(".")
    .reduce<unknown>(
      (node, key) =>
        node !== null && typeof node === "object"
          ? (node as Record<string, unknown>)[key]
          : undefined,
      englishMessages
    );
  expect({ key: path, type: typeof raw }).toEqual({
    key: path,
    type: "string",
  });
  return raw as string;
}

const TAB_CONFIGURATIONS = "admin.connector.tabs.configurations";
const TAB_INDEXING = "admin.connector.tabs.indexing";
const TAB_INDEXING_DISABLED = "admin.connector.tabs.indexingDisabled";
const CHART_HEADING = "admin.connector.indexingTab.chartHeading";
const RUNS_HEADING = "admin.connector.indexingTab.runsHeading";
const RUNS_EMPTY = "admin.connector.runs.empty.title";
const MENU = {
  trigger: "admin.connector.manageMenu.trigger.label",
  startIndexing: "admin.connector.manageMenu.startIndexing.label",
  updateIndex: "admin.connector.manageMenu.updateIndex.label",
  syncPermissions: "admin.connector.manageMenu.syncPermissions.label",
  syncPermissionsDescription:
    "admin.connector.manageMenu.syncPermissions.description",
  fullReindex: "admin.connector.manageMenu.fullReindex.label",
  pause: "admin.connector.manageMenu.toggleStatus.pause.label",
  resume: "admin.connector.manageMenu.toggleStatus.resume.label",
  delete: "admin.connector.manageMenu.delete.label",
  deleteDescription: "admin.connector.manageMenu.delete.description",
};

// ── Fixtures ────────────────────────────────────────────────────────────────

function isoAgo(ms: number): string {
  return new Date(NOW - ms).toISOString();
}

/** An active, permission-synced Confluence pair that has indexed before. */
function ccPair(overrides: Partial<CCPairFullInfo> = {}): CCPairFullInfo {
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
      access_type: "sync",
      credential_ids: [12],
      time_created: isoAgo(90 * 24 * 60 * MINUTE_MS),
      time_updated: isoAgo(90 * 24 * 60 * MINUTE_MS),
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
      time_created: isoAgo(90 * 24 * 60 * MINUTE_MS),
      time_updated: isoAgo(90 * 24 * 60 * MINUTE_MS),
    },
    number_of_index_attempts: 15,
    last_index_attempt_status: "success",
    latest_deletion_attempt: null,
    access_type: "sync",
    is_editable_for_current_user: true,
    permissions: { operate: true, edit: true, delete: true },
    deletion_failure_message: null,
    indexing: false,
    creator: null,
    creator_email: null,
    last_indexed: isoAgo(2 * MINUTE_MS),
    last_pruned: null,
    last_full_permission_sync: null,
    last_time_perm_sync: isoAgo(2 * MINUTE_MS),
    last_time_external_group_sync: null,
    overall_indexing_speed: null,
    latest_checkpoint_description: null,
    last_permission_sync_attempt_status: null,
    permission_syncing: false,
    last_permission_sync_attempt_finished: null,
    last_permission_sync_attempt_error_message: null,
    supports_doc_permission_sync: true,
    supports_targeted_reindex: true,
    pending_backfills: [],
    has_named_checks: false,
    indexing_hold: null,
    ...overrides,
  } as CCPairFullInfo;
}

/** No run has started yet: the pair waits for its first index. */
const NEVER_RUN: Partial<CCPairFullInfo> = {
  status: ConnectorCredentialPairStatus.SCHEDULED,
  num_docs_indexed: 0,
  number_of_index_attempts: 0,
  last_index_attempt_status: null,
  last_indexed: null,
  last_time_perm_sync: null,
};

/** A public pair, so its source has no permission sync. */
const PUBLIC: Partial<CCPairFullInfo> = {
  access_type: "public",
  supports_doc_permission_sync: false,
};

function indexRun(id: number): CCPairRun {
  return {
    kind: "indexing",
    time_created: isoAgo(id * 10 * MINUTE_MS),
    resolved_at: null,
    superseded: false,
    is_retry: false,
    attempt: {
      id,
      status: "success",
      from_beginning: false,
      new_docs_indexed: 25,
      docs_removed_from_index: 0,
      total_docs_indexed: 25,
      error_msg: null,
      error_count: 0,
      open_error_count: 0,
      open_doc_error_count: 0,
      full_exception_trace: null,
      time_started: isoAgo(id * 10 * MINUTE_MS),
      time_updated: isoAgo(id * 10 * MINUTE_MS - 5 * MINUTE_MS),
      time_finished: isoAgo(id * 10 * MINUTE_MS - 5 * MINUTE_MS),
      is_new_model: false,
      is_backfill: false,
    },
  } as CCPairRun;
}

function runsResponse(items: CCPairRun[], total = items.length) {
  return {
    items,
    total_items: total,
    kinds: ["indexing", "doc_permission_sync", "group_sync"],
    status_counts: {
      running: 0,
      succeeded: items.length,
      failed: 0,
      canceled: 0,
    },
  } as CCPairRunsResponse;
}

const SLICES = 24;

function throughput(withData: boolean): CCPairThroughputResponse {
  return {
    window_start: isoAgo(24 * 60 * MINUTE_MS),
    window_end: new Date(NOW).toISOString(),
    docs_indexed: Array.from({ length: SLICES }, (_, index) =>
      withData && index % 3 === 0 ? 40 : 0
    ),
    runs: withData
      ? [
          {
            started: isoAgo(30 * MINUTE_MS),
            ended: isoAgo(25 * MINUTE_MS),
            status: "success",
          },
        ]
      : [],
  };
}

// ── API stub ────────────────────────────────────────────────────────────────

interface Setup {
  pair?: CCPairFullInfo | null;
  /** Runs inside the picked window. */
  runs?: CCPairRun[];
  /** Runs of the pair over all time, read by the empty window's "Past Runs". */
  allTimeRuns?: number;
  chartData?: boolean;
  query?: string;
}

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

const realFetch = global.fetch;
afterEach(() => {
  global.fetch = realFetch;
  mockQuery = new URLSearchParams();
  window.history.replaceState(null, "", "/");
});

/** Serves the pair, its runs feed, its throughput and its latest attempt. Anything else stays pending. A null pair never loads. */
function stubApi({
  pair = ccPair(),
  runs = [indexRun(1), indexRun(2)],
  allTimeRuns,
  chartData = true,
}: Setup) {
  global.fetch = jest.fn((input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://localhost");
    const path = url.pathname;
    const base = `/api/manage/admin/cc-pair/${CC_PAIR_ID}`;
    if (path === base && pair !== null) {
      return Promise.resolve(jsonResponse(pair));
    }
    if (path === `${base}/runs`) {
      const windowed = url.searchParams.has("since");
      return Promise.resolve(
        jsonResponse(
          windowed || allTimeRuns === undefined
            ? runsResponse(runs)
            : runsResponse(runs, allTimeRuns)
        )
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

async function renderPage(setup: Setup = {}) {
  const query = setup.query ?? "";
  mockQuery = new URLSearchParams(query);
  window.history.replaceState(
    null,
    "",
    `/admin/connector/${CC_PAIR_ID}${query ? `?${query}` : ""}`
  );
  stubApi(setup);
  const params = Promise.resolve({ ccPairId: String(CC_PAIR_ID) });
  // The page reads its params with `use`, which suspends once.
  let view: ReturnType<typeof render> | undefined;
  await act(async () => {
    view = render(
      <Suspense fallback={null}>
        <ConnectorDetailPage params={params} />
      </Suspense>
    );
  });
  return view as ReturnType<typeof render>;
}

/** Waits for the pair to load: its name is the page title. */
async function loaded() {
  await screen.findAllByText("Policy knowledge");
}

function tab(key: string): HTMLElement {
  return screen.getByRole("tab", { name: copy(key) });
}

/** The panel the tab controls. */
function panelOf(tabElement: HTMLElement): HTMLElement {
  const id = tabElement.getAttribute("aria-controls");
  expect(id).not.toBeNull();
  const panel = document.getElementById(id as string);
  expect(panel).not.toBeNull();
  return panel as HTMLElement;
}

/** True when `later` comes after `earlier` in document order. */
function follows(earlier: Node, later: Node): boolean {
  return Boolean(
    earlier.compareDocumentPosition(later) & Node.DOCUMENT_POSITION_FOLLOWING
  );
}

/** Lets pending fetches resolve and SWR commit them. */
async function settle() {
  for (let step = 0; step < 5; step++) {
    await act(async () => {
      await Promise.resolve();
    });
  }
}

// ── Tabs ────────────────────────────────────────────────────────────────────

describe("connector page tabs", () => {
  it("opens on Connector Configurations, which holds the Account, Index Configurations, Sharing and Schedule sections", async () => {
    await renderPage();
    await loaded();
    const configurations = await screen.findByRole("tab", {
      name: copy(TAB_CONFIGURATIONS),
    });
    const indexing = tab(TAB_INDEXING);
    expect(configurations).toHaveAttribute("aria-selected", "true");
    expect(indexing).toHaveAttribute("aria-selected", "false");

    const panel = panelOf(configurations);
    for (const title of [
      copy("admin.connector.account.title"),
      copy("admin.connector.configuration.title"),
      copy("admin.connector.sharing.title"),
      copy("admin.connectorsList.scheduled.title"),
    ]) {
      expect(within(panel).getAllByText(title).length).toBeGreaterThan(0);
    }
    // The Indexing tab's cards are not part of this tab.
    expect(within(panel).queryByText(copy(RUNS_HEADING))).toBeNull();
    expect(within(panel).queryByTestId("connector-runs")).toBeNull();
  });

  it("the tabs sit in one tab list, Connector Configurations first", async () => {
    await renderPage();
    await loaded();
    const list = await screen.findByRole("tablist");
    const tabs = within(list).getAllByRole("tab");
    expect(tabs.map((element) => element.textContent?.trim())).toEqual([
      copy(TAB_CONFIGURATIONS),
      copy(TAB_INDEXING),
    ]);
  });

  it("a click on Indexing shows the Document Indexing and Indexing Runs cards in place of the configuration sections", async () => {
    const user = setupUser();
    await renderPage();
    await loaded();
    await user.click(
      await screen.findByRole("tab", { name: copy(TAB_INDEXING) })
    );
    const indexing = tab(TAB_INDEXING);
    expect(indexing).toHaveAttribute("aria-selected", "true");
    const panel = panelOf(indexing);
    expect(
      await within(panel).findByText(copy(RUNS_HEADING))
    ).toBeInTheDocument();
    expect(within(panel).getByTestId("connector-runs")).toBeInTheDocument();
    expect(
      within(panel).queryByText(copy("admin.connector.sharing.title"))
    ).toBeNull();
  });

  it("?tab=indexing opens the page on the Indexing tab", async () => {
    await renderPage({ query: "tab=indexing" });
    await loaded();
    const indexing = await screen.findByRole("tab", {
      name: copy(TAB_INDEXING),
    });
    await waitFor(() =>
      expect(indexing).toHaveAttribute("aria-selected", "true")
    );
    expect(tab(TAB_CONFIGURATIONS)).toHaveAttribute("aria-selected", "false");
    const panel = panelOf(indexing);
    expect(
      await within(panel).findByText(copy(RUNS_HEADING))
    ).toBeInTheDocument();
    expect(within(panel).getByTestId("connector-runs")).toBeInTheDocument();
  });

  it("a same-page link to ?tab=indexing, and Back from it, switch the tab without a remount", async () => {
    const view = await renderPage();
    await loaded();
    expect(tab(TAB_CONFIGURATIONS)).toHaveAttribute("aria-selected", "true");
    const rerenderAt = async (query: string) => {
      mockQuery = new URLSearchParams(query);
      const params = Promise.resolve({ ccPairId: String(CC_PAIR_ID) });
      await act(async () => {
        view.rerender(
          <Suspense fallback={null}>
            <ConnectorDetailPage params={params} />
          </Suspense>
        );
      });
    };

    await rerenderAt("tab=indexing");
    await waitFor(() =>
      expect(tab(TAB_INDEXING)).toHaveAttribute("aria-selected", "true")
    );
    expect(
      within(panelOf(tab(TAB_INDEXING))).getByTestId("connector-runs")
    ).toBeInTheDocument();

    await rerenderAt("");
    await waitFor(() =>
      expect(tab(TAB_CONFIGURATIONS)).toHaveAttribute("aria-selected", "true")
    );
  });

  it("before the first run starts the Indexing tab is disabled with the tooltip Available after the first run starts.", async () => {
    const user = setupUser();
    await renderPage({ pair: ccPair(NEVER_RUN), runs: [] });
    await loaded();
    const indexing = await screen.findByRole("tab", {
      name: copy(TAB_INDEXING),
    });
    expect(indexing).toBeDisabled();
    expect(tab(TAB_CONFIGURATIONS)).toHaveAttribute("aria-selected", "true");

    // A disabled button gets no pointer events, so the tooltip hangs on its wrapper.
    await user.hover(indexing.parentElement as HTMLElement);
    const tooltip = await screen.findByRole("tooltip", {}, { timeout: 3000 });
    expect(tooltip).toHaveTextContent(copy(TAB_INDEXING_DISABLED));
  });

  it("an indexed pair's Indexing tab is enabled", async () => {
    await renderPage();
    await loaded();
    const indexing = await screen.findByRole("tab", {
      name: copy(TAB_INDEXING),
    });
    expect(indexing).toBeEnabled();
  });

  it("before the first run starts, ?tab=indexing falls back to Connector Configurations", async () => {
    await renderPage({
      pair: ccPair(NEVER_RUN),
      runs: [],
      query: "tab=indexing",
    });
    await loaded();
    const configurations = await screen.findByRole("tab", {
      name: copy(TAB_CONFIGURATIONS),
    });
    await settle();
    expect(configurations).toHaveAttribute("aria-selected", "true");
    expect(tab(TAB_INDEXING)).toHaveAttribute("aria-selected", "false");
    expect(
      within(panelOf(configurations)).getAllByText(
        copy("admin.connector.sharing.title")
      ).length
    ).toBeGreaterThan(0);
  });

  it("Loading: the tab strip shows before the pair loads, with both tabs disabled", async () => {
    await renderPage({ pair: null });
    const configurations = await screen.findByRole("tab", {
      name: copy(TAB_CONFIGURATIONS),
    });
    expect(configurations).toBeDisabled();
    expect(tab(TAB_INDEXING)).toBeDisabled();
  });
});

// ── Indexing tab content ────────────────────────────────────────────────────

describe("connector page Indexing tab", () => {
  // The chart fetches once its width is measured, which jsdom never lays out.
  beforeEach(() => installChartLayout(600));
  afterEach(resetChartLayout);

  it("Document Indexing heads the chart card, then Indexing Runs heads the runs card, both under the Indexing tab", async () => {
    await renderPage({ query: "tab=indexing" });
    await loaded();
    const indexing = await screen.findByRole("tab", {
      name: copy(TAB_INDEXING),
    });
    await waitFor(() =>
      expect(indexing).toHaveAttribute("aria-selected", "true")
    );
    const panel = panelOf(indexing);
    const chartHeading = await within(panel).findByText(copy(CHART_HEADING));
    const runsHeading = within(panel).getByText(copy(RUNS_HEADING));
    const runsCard = within(panel).getByTestId("connector-runs");
    expect(follows(chartHeading, runsHeading)).toBe(true);
    expect(follows(runsHeading, runsCard)).toBe(true);
  });

  it("the chart leaves the status card for the Indexing tab", async () => {
    await renderPage({ query: "tab=indexing" });
    await loaded();
    const indexing = await screen.findByRole("tab", {
      name: copy(TAB_INDEXING),
    });
    await waitFor(() =>
      expect(indexing).toHaveAttribute("aria-selected", "true")
    );
    await within(panelOf(indexing)).findByText(copy(CHART_HEADING));
    const statusCard = screen.getByTestId("connector-indexing-status");
    expect(statusCard).not.toContainElement(
      within(panelOf(indexing)).getByText(copy(CHART_HEADING))
    );
    expect(
      within(statusCard).queryByRole("img", {
        name: copy("admin.connector.statusCard.throughput.ariaLabel"),
      })
    ).toBeNull();
  });

  it("with no throughput data in the window the chart card is hidden and the runs card stays", async () => {
    await renderPage({ query: "tab=indexing", chartData: false });
    await loaded();
    const indexing = await screen.findByRole("tab", {
      name: copy(TAB_INDEXING),
    });
    await waitFor(() =>
      expect(indexing).toHaveAttribute("aria-selected", "true")
    );
    const panel = panelOf(indexing);
    await within(panel).findByText(copy(RUNS_HEADING));
    await waitFor(() =>
      expect(
        jest
          .mocked(global.fetch)
          .mock.calls.some(([input]) =>
            String(input).includes(`/cc-pair/${CC_PAIR_ID}/throughput`)
          )
      ).toBe(true)
    );
    await settle();
    expect(screen.queryByText(copy(CHART_HEADING))).toBeNull();
    expect(within(panel).getByTestId("connector-runs")).toBeInTheDocument();
  });

  it("with no runs in the window the runs card shows the long-wait illustration at 64 over No recent indexing runs", async () => {
    await renderPage({
      query: "tab=indexing",
      runs: [],
      allTimeRuns: 120,
      chartData: false,
    });
    await loaded();
    const indexing = await screen.findByRole("tab", {
      name: copy(TAB_INDEXING),
    });
    await waitFor(() =>
      expect(indexing).toHaveAttribute("aria-selected", "true")
    );
    const runsCard = await within(panelOf(indexing)).findByTestId(
      "connector-runs"
    );
    const title = await within(runsCard).findByText(copy(RUNS_EMPTY));

    const reference = render(<SvgLongWait size={64} />).container.querySelector(
      "svg"
    ) as SVGSVGElement;
    const referencePaths = Array.from(reference.querySelectorAll("path")).map(
      (path) => path.getAttribute("d")
    );
    const illustration = Array.from(runsCard.querySelectorAll("svg")).find(
      (svg) => {
        const paths = Array.from(svg.querySelectorAll("path")).map((path) =>
          path.getAttribute("d")
        );
        return (
          paths.length === referencePaths.length &&
          paths.every((d, index) => d === referencePaths[index])
        );
      }
    );
    expect(illustration).toBeDefined();
    const svg = illustration as SVGSVGElement;
    expect(svg.getAttribute("width")).toBe("64");
    expect(svg.getAttribute("height")).toBe("64");
    expect(svg.getAttribute("stroke-width")).toBe(
      reference.getAttribute("stroke-width")
    );
    // The illustration sits over the title.
    expect(follows(svg, title)).toBe(true);
  });
});

// ── Manage Index menu ───────────────────────────────────────────────────────

/** Opens Manage Index and returns its items in order, by their titles. */
async function openMenu(): Promise<HTMLElement[]> {
  const user = setupUser();
  await loaded();
  await user.click(
    await screen.findByRole("button", { name: copy(MENU.trigger) })
  );
  await screen.findByRole("menu");
  return screen.getAllByRole("menuitem");
}

/** Asserts the menu holds exactly these titles in this order. */
function expectItems(items: HTMLElement[], keys: string[]) {
  const titles = keys.map(copy);
  const found = titles.map((title) =>
    items.findIndex((item) => item.textContent?.includes(title))
  );
  expect({ titles, found }).toEqual({
    titles,
    found: titles.map((_, index) => index),
  });
  expect(items).toHaveLength(titles.length);
}

/** Delete Connector closes every menu, danger, with its description, and the menu's one divider sits right above it. */
function expectDeleteLast(items: HTMLElement[]) {
  const deleteItem = items[items.length - 1] as HTMLElement;
  expect(deleteItem).toHaveTextContent(copy(MENU.delete));
  expect(deleteItem).toHaveTextContent(copy(MENU.deleteDescription));
  const dividers = screen.getByRole("menu").querySelectorAll(".opal-divider");
  expect(dividers).toHaveLength(1);
  const divider = dividers[0] as Element;
  expect(follows(divider, deleteItem)).toBe(true);
  for (const item of items.slice(0, -1)) {
    expect(follows(item, divider)).toBe(true);
  }
}

function expectNoDisconnect(items: HTMLElement[]) {
  for (const item of items) {
    expect(item.textContent ?? "").not.toMatch(/disconnect/i);
  }
}

describe("Manage Index menu by state", () => {
  it("an active permission-synced pair reads Update Index, Sync Permissions, Full Re-index, Pause Indexing & Syncs, divider, Delete Connector", async () => {
    await renderPage();
    const items = await openMenu();
    expectItems(items, [
      MENU.updateIndex,
      MENU.syncPermissions,
      MENU.fullReindex,
      MENU.pause,
      MENU.delete,
    ]);
    expect(items[1]).toHaveTextContent(copy(MENU.syncPermissionsDescription));
    expectDeleteLast(items);
    expectNoDisconnect(items);
  });

  it("an active pair without permission sync has no Sync Permissions", async () => {
    await renderPage({ pair: ccPair(PUBLIC) });
    const items = await openMenu();
    expectItems(items, [
      MENU.updateIndex,
      MENU.fullReindex,
      MENU.pause,
      MENU.delete,
    ]);
    expectDeleteLast(items);
  });

  it("an indexing pair keeps the active order", async () => {
    await renderPage({ pair: ccPair({ indexing: true }) });
    const items = await openMenu();
    expectItems(items, [
      MENU.updateIndex,
      MENU.syncPermissions,
      MENU.fullReindex,
      MENU.pause,
      MENU.delete,
    ]);
    expectDeleteLast(items);
    expectNoDisconnect(items);
  });

  it("a failed pair keeps the active order", async () => {
    await renderPage({
      pair: ccPair({
        in_repeated_error_state: true,
        last_index_attempt_status: "failed",
      }),
    });
    const items = await openMenu();
    expectItems(items, [
      MENU.updateIndex,
      MENU.syncPermissions,
      MENU.fullReindex,
      MENU.pause,
      MENU.delete,
    ]);
    expectDeleteLast(items);
  });

  it("a paused pair reads Resume Indexing & Syncs, divider, Delete Connector, and no Disconnect", async () => {
    await renderPage({
      pair: ccPair({ status: ConnectorCredentialPairStatus.PAUSED }),
    });
    const items = await openMenu();
    expectItems(items, [MENU.resume, MENU.delete]);
    expectDeleteLast(items);
    expectNoDisconnect(items);
  });

  it("before the first index starts there is no Update Index or Full Re-index", async () => {
    await renderPage({ pair: ccPair(NEVER_RUN), runs: [] });
    const items = await openMenu();
    expectItems(items, [MENU.syncPermissions, MENU.pause, MENU.delete]);
    expectDeleteLast(items);
  });

  it("a held pair before its first index also offers Start Indexing", async () => {
    await renderPage({
      pair: ccPair({
        ...NEVER_RUN,
        ...PUBLIC,
        indexing_hold: {
          reason: "required_checks_failed",
          checks: [],
        } as unknown as CCPairFullInfo["indexing_hold"],
      }),
      runs: [],
    });
    const items = await openMenu();
    expectItems(items, [MENU.startIndexing, MENU.pause, MENU.delete]);
    expectDeleteLast(items);
  });

  it("the changed and new menu copy reads as the spec says", () => {
    expect(copy(MENU.delete)).toBe("Delete Connector");
    expect(copy(MENU.deleteDescription)).toBe(
      "Permanently remove all indexed docs."
    );
    expect(copy(MENU.syncPermissionsDescription)).toBe(
      "Pull doc permissions from the source."
    );
    expect(copy(TAB_CONFIGURATIONS)).toBe("Connector Configurations");
    expect(copy(TAB_INDEXING)).toBe("Indexing");
    expect(copy(TAB_INDEXING_DISABLED)).toBe(
      "Available after the first run starts."
    );
    expect(copy(CHART_HEADING)).toBe("Document Indexing");
    expect(copy(RUNS_HEADING)).toBe("Indexing Runs");
    expect(copy(RUNS_EMPTY)).toBe("No recent indexing runs");
  });
});

// ── Layout ──────────────────────────────────────────────────────────────────

/** `@max-[51rem]:flex-col` and the like: a container query that stacks below roughly 816 px. */
const STACK_BELOW_816 = /^@max-\[([\d.]+)(rem|px)\](\/[\w-]+)?:flex-col$/;

function stackBreakpointPx(className: string): number | null {
  const match = className.match(STACK_BELOW_816);
  if (match === null) return null;
  const value = Number(match[1]);
  return match[2] === "rem" ? value * 16 : value;
}

describe("connector page layout", () => {
  it("below 816 px content width the column and the Activities panel stack, by a container query, with the panel last", async () => {
    await renderPage();
    await loaded();
    const tabs = await screen.findByRole("tablist");
    const panel = screen.getByTestId("connector-activity");
    // The panel comes after the column.
    expect(follows(tabs, panel)).toBe(true);

    let row: HTMLElement | null = tabs.parentElement;
    while (row !== null && !row.contains(panel)) row = row.parentElement;
    expect(row).not.toBeNull();

    // The row holding both, or an ancestor of it, stacks below about 816 px of its container.
    let stacking: { element: HTMLElement; name: string | undefined } | null =
      null;
    for (
      let element: HTMLElement | null = row;
      element !== null && stacking === null;
      element = element.parentElement
    ) {
      for (const className of Array.from(element.classList)) {
        const px = stackBreakpointPx(className);
        if (px !== null && px >= 800 && px <= 816) {
          stacking = {
            element,
            name: className.match(STACK_BELOW_816)?.[3]?.slice(1),
          };
        }
      }
    }
    expect(stacking).not.toBeNull();
    const { element, name } = stacking as {
      element: HTMLElement;
      name: string | undefined;
    };
    // The content width decides, not the viewport.
    expect(element.className).not.toMatch(/max-lg:flex-col/);

    const containerClass =
      name === undefined ? "@container" : `@container/${name}`;
    let container: HTMLElement | null = element.parentElement;
    while (
      container !== null &&
      !container.classList.contains(containerClass)
    ) {
      container = container.parentElement;
    }
    expect(container).not.toBeNull();
  });
});

// ── Layout edges ────────────────────────────────────────────────────────────

describe("connector page layout edges", () => {
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

  // The chart fetches once its width is measured, which jsdom never lays out.
  beforeEach(() => installChartLayout(600));
  afterEach(resetChartLayout);

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

// ── Status cards (PR 16) ────────────────────────────────────────────────────

function pruneRun(id: number): CCPairRun {
  return {
    kind: "pruning",
    time_created: isoAgo(60 * MINUTE_MS),
    resolved_at: null,
    superseded: false,
    attempt: {
      id,
      status: "success",
      docs_removed: 15,
      docs_failed: 0,
      error_message: null,
      time_created: isoAgo(60 * MINUTE_MS),
      time_started: isoAgo(60 * MINUTE_MS),
      time_finished: isoAgo(58 * MINUTE_MS),
    },
  };
}

/** Every URL the page has routed to: the address bar and the router's pushes and replaces. */
function routedUrls(): URL[] {
  return [
    window.location.href,
    ...mockPush.mock.calls.map((call) => String(call[0])),
    ...mockReplace.mock.calls.map((call) => String(call[0])),
  ].map((href) => new URL(href, "http://localhost/admin/connector/7"));
}

describe("connector page status cards", () => {
  beforeEach(() => {
    mockPush.mockClear();
    mockReplace.mockClear();
  });

  it("AC-2, D-67: View Pruning Run on the status card opens the Indexing tab at that run", async () => {
    const user = setupUser();
    await renderPage({ runs: [pruneRun(44)] });
    await loaded();
    await settle();

    const [indexingCard] = await screen.findAllByTestId("status-card");
    const prune = await within(indexingCard!).findByRole("button", {
      name: copy("admin.connector.statusCard.actions.viewPruningRun"),
    });
    await user.click(prune);

    await waitFor(() =>
      expect(tab(TAB_INDEXING)).toHaveAttribute("aria-selected", "true")
    );
    await waitFor(() =>
      expect(
        routedUrls().some(
          (url) =>
            url.searchParams.get("tab") === "indexing" &&
            url.searchParams.get("run") === "44" &&
            url.searchParams.get("run_kind") === "pruning"
        )
      ).toBe(true)
    );
  });

  it("D-62: the status card's Activities panel button hides and shows the panel", async () => {
    const user = setupUser();
    await renderPage();
    await loaded();
    await settle();

    const hide = copy("admin.connector.statusCard.actions.hideActivities");
    const show = copy("admin.connector.statusCard.actions.showActivities");
    const [indexingCard] = await screen.findAllByTestId("status-card");
    expect(screen.getByTestId("connector-activity")).toBeInTheDocument();

    await user.click(within(indexingCard!).getByRole("button", { name: hide }));
    await waitFor(() =>
      expect(screen.queryByTestId("connector-activity")).toBeNull()
    );

    await user.click(
      within(screen.getAllByTestId("status-card")[0]!).getByRole("button", {
        name: show,
      })
    );
    await waitFor(() =>
      expect(screen.getByTestId("connector-activity")).toBeInTheDocument()
    );
  });
});
