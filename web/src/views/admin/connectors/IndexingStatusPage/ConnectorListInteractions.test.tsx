/** The toolbar pills filter the list by status and toggle off, a private row whose groups the viewer cannot see reads "Private", one row opens at a time, and an expanded row with no runs in its window points to the older ones. */
import {
  copy,
  makeConnectorRow,
  makeConnectorsPage,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import type {
  CCPairRun,
  CCPairRunsResponse,
  IndexingConnectorsResponse,
} from "@/lib/connectors/types";
import ConnectorList from "@/views/admin/connectors/IndexingStatusPage/ConnectorList";

const CONNECTORS_PATH = "/api/manage/admin/index-monitoring/connectors";
const EXPAND = "admin.indexing.list.actions.expand";
const RUNS_PATH = "/api/manage/admin/cc-pair/1/runs";
const HOUR_MS = 60 * 60 * 1000;
const THREE_DAYS_MS = 72 * HOUR_MS;

// A finished run older than the expanded row's default 24 h window.
const OLD_RUN = {
  kind: "indexing",
  time_created: new Date(Date.now() - THREE_DAYS_MS).toISOString(),
  resolved_at: null,
  superseded: false,
  is_retry: false,
  attempt: {
    id: 9,
    status: "success",
    from_beginning: false,
    new_docs_indexed: 10,
    docs_removed_from_index: 0,
    total_docs_indexed: 10,
    error_msg: null,
    error_count: 0,
    open_error_count: 0,
    open_doc_error_count: 0,
    full_exception_trace: null,
    time_started: new Date(Date.now() - THREE_DAYS_MS).toISOString(),
    time_updated: new Date(Date.now() - THREE_DAYS_MS).toISOString(),
    time_finished: new Date(Date.now() - THREE_DAYS_MS).toISOString(),
    is_new_model: false,
    is_backfill: false,
  },
} as CCPairRun;

/** Runs in a windowed query are empty; unwindowed, the pair has 120 older runs. */
function runsFor(url: URL): CCPairRunsResponse {
  const windowed = url.searchParams.has("since");
  return {
    items: windowed ? [] : [OLD_RUN],
    total_items: windowed ? 0 : 120,
    kinds: ["indexing"],
    status_counts: { running: 0, succeeded: 120, failed: 0, canceled: 0 },
  } as unknown as CCPairRunsResponse;
}

function jsonResponse(body: unknown): Promise<Response> {
  return Promise.resolve({
    ok: true,
    status: 200,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response);
}

let page: IndexingConnectorsResponse = makeConnectorsPage([]);
let statusParams: (string | null)[] = [];
let runsUrls: URL[] = [];
let runsFail = false;
const realFetch = global.fetch;
beforeEach(() => {
  statusParams = [];
  runsUrls = [];
  runsFail = false;
  global.fetch = jest.fn((input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://localhost");
    if (url.pathname === RUNS_PATH) {
      runsUrls.push(url);
      if (!runsFail) return jsonResponse(runsFor(url));
      return Promise.resolve({
        ok: false,
        status: 500,
        json: async () => ({ detail: "boom" }),
        text: async () => JSON.stringify({ detail: "boom" }),
      } as unknown as Response);
    }
    if (url.pathname !== CONNECTORS_PATH) {
      return new Promise<Response>(() => {});
    }
    statusParams.push(url.searchParams.get("status"));
    return jsonResponse(page);
  }) as typeof fetch;
});
afterEach(() => {
  global.fetch = realFetch;
});

function renderList() {
  render(
    <ConnectorList
      onViewLogs={jest.fn()}
      onFocusError={jest.fn()}
      onFocusChange={jest.fn()}
    />
  );
}

describe("ConnectorList pills", () => {
  it("filters to a pill's status, shows it pressed, and clears on a second click", async () => {
    page = makeConnectorsPage([makeConnectorRow({ status: "failed" })]);
    renderList();
    const pill = await screen.findByRole("button", {
      name: "1 connector failed",
    });
    expect(pill).toHaveAttribute("aria-pressed", "false");

    await setupUser().click(pill);
    await waitFor(() => expect(statusParams).toContain("failed"));
    expect(
      screen.getByRole("button", { name: "1 connector failed" })
    ).toHaveAttribute("aria-pressed", "true");

    const callsBefore = statusParams.length;
    await setupUser().click(
      screen.getByRole("button", { name: "1 connector failed" })
    );
    await waitFor(() =>
      expect(statusParams.slice(callsBefore)).toContain(null)
    );
  });
});

describe("ConnectorList rows", () => {
  it("reads a private row with no visible groups as Private", async () => {
    page = makeConnectorsPage([
      makeConnectorRow({ access_type: "private", group_count: 0 }),
    ]);
    renderList();

    expect(await screen.findByText("Private")).toBeInTheDocument();
    expect(screen.queryByText(/Shared with/)).not.toBeInTheDocument();
  });

  it("keeps one row expanded, so opening another closes the first", async () => {
    page = makeConnectorsPage([
      makeConnectorRow({ cc_pair_id: 1, name: "Sales Mailbox" }),
      makeConnectorRow({ cc_pair_id: 2, name: "Support Mailbox" }),
    ]);
    renderList();
    const [first, second] = await screen.findAllByRole("button", {
      name: copy(EXPAND),
    });

    await setupUser().click(first!);
    expect(screen.getAllByTestId("connector-runs")).toHaveLength(1);
    await setupUser().click(second!);

    expect(screen.getAllByTestId("connector-runs")).toHaveLength(1);
    expect(
      screen
        .getByTestId("indexing-connector-2")
        .querySelector('[data-testid="connector-runs"]')
    ).not.toBeNull();
  });

  it("points an expanded row with no runs in its window to the older runs, and shows them on View", async () => {
    page = makeConnectorsPage([makeConnectorRow()]);
    renderList();
    await setupUser().click(
      await screen.findByRole("button", { name: copy(EXPAND) })
    );

    expect(await screen.findByText("120 Past Runs")).toBeInTheDocument();
    expect(screen.queryAllByTestId("run-row")).toHaveLength(0);
    await setupUser().click(
      screen.getByRole("button", { name: "View 120 past runs" })
    );

    expect(await screen.findAllByTestId("run-row")).toHaveLength(1);
  });

  it("opens the expanded row's runs on the last 24 hours", async () => {
    page = makeConnectorsPage([makeConnectorRow()]);
    renderList();
    await setupUser().click(
      await screen.findByRole("button", { name: copy(EXPAND) })
    );

    await waitFor(() =>
      expect(
        runsUrls.some((url) => !url.searchParams.has("status_groups"))
      ).toBe(true)
    );
    const listRequest = runsUrls.find(
      (url) => !url.searchParams.has("status_groups")
    )!;
    const since = Date.parse(listRequest.searchParams.get("since") ?? "");
    expect(Math.abs(since - (Date.now() - 24 * HOUR_MS))).toBeLessThan(
      2 * HOUR_MS
    );
  });

  it("offers Retry on a failed runs load and reloads the runs with it", async () => {
    runsFail = true;
    page = makeConnectorsPage([makeConnectorRow()]);
    renderList();
    await setupUser().click(
      await screen.findByRole("button", { name: copy(EXPAND) })
    );
    const retry = await screen.findByRole("button", {
      name: copy("admin.connector.runs.loadError.retry"),
    });

    runsFail = false;
    const requestsBefore = runsUrls.length;
    await setupUser().click(retry);

    await waitFor(() =>
      expect(runsUrls.length).toBeGreaterThan(requestsBefore)
    );
    expect(await screen.findByText("120 Past Runs")).toBeInTheDocument();
  });
});
