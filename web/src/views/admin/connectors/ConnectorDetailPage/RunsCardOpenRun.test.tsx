/** A run the page's address points at opens its inline details, widening a list that misses it and paging back to it, and only runs with details open. An empty window's past runs row widens the list. */
import {
  copy,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import type {
  CCPairRun,
  CCPairRunsResponse,
  CheckRunSnapshot,
} from "@/lib/connectors/types";
import type { CapabilityCheckResult } from "@/lib/connectors/checks/types";
import RunsCard from "@/views/admin/connectors/ConnectorDetailPage/RunsCard";
import type { RunRef } from "@/views/admin/connectors/ConnectorDetailPage/runLink";

const CC_PAIR_ID = 7;
const MINUTE_MS = 60_000;
const START = "2026-03-23T10:00:00.000Z";

function isoAfter(iso: string, ms: number): string {
  return new Date(new Date(iso).getTime() + ms).toISOString();
}

const CLOSE_STAGES = copy("admin.connector.stageDetails.close");
const CLOSE_CHECKS = copy("admin.connector.runs.checkResults.close");

function indexRun(id: number): CCPairRun {
  return {
    kind: "indexing",
    time_created: isoAfter(START, -id * MINUTE_MS),
    resolved_at: null,
    superseded: false,
    is_retry: false,
    attempt: {
      id,
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
      time_started: START,
      time_updated: isoAfter(START, 5 * MINUTE_MS),
      time_finished: isoAfter(START, 5 * MINUTE_MS),
      is_new_model: false,
      is_backfill: false,
    },
  };
}

function failedCheck(): CapabilityCheckResult {
  return {
    capability: "indexing",
    check_id: "a",
    display_name: "Check a",
    required: false,
    status: "failed",
    message: "Check a failed",
    summary: null,
    description: null,
    error_kind: null,
    not_run_reason: null,
    applicable: true,
    remediation: null,
    docs_link: null,
    duration_ms: 10,
    findings: [],
  };
}

const CHECK_ATTEMPT: CheckRunSnapshot = {
  id: 9,
  status: "failed",
  trigger: "manual",
  check_results: [failedCheck()],
  error_message: null,
  time_created: START,
  time_started: START,
  time_finished: isoAfter(START, MINUTE_MS),
};

const CHECK_RUN: CCPairRun = {
  kind: "checks",
  time_created: isoAfter(START, -9 * MINUTE_MS),
  resolved_at: null,
  superseded: false,
  attempt: CHECK_ATTEMPT,
};

const PRUNE_RUN: CCPairRun = {
  kind: "pruning",
  time_created: isoAfter(START, -12 * MINUTE_MS),
  resolved_at: null,
  superseded: false,
  attempt: {
    id: 1,
    status: "success",
    docs_removed: 3,
    docs_failed: 0,
    error_message: null,
    time_created: START,
    time_started: START,
    time_finished: isoAfter(START, MINUTE_MS),
  },
};

const RUNS: CCPairRun[] = [indexRun(1), indexRun(2), CHECK_RUN, PRUNE_RUN];

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

const realFetch = global.fetch;
beforeEach(() => {
  const response: CCPairRunsResponse = {
    items: RUNS,
    total_items: RUNS.length,
    kinds: ["indexing", "checks", "pruning"],
    status_counts: {
      running: 0,
      succeeded: RUNS.length,
      failed: 0,
      canceled: 0,
    },
  };
  // The runs feed answers; stage metrics and anything else stay pending.
  global.fetch = jest.fn((input: RequestInfo | URL) =>
    String(input).includes(`/cc-pair/${CC_PAIR_ID}/runs?`)
      ? Promise.resolve(jsonResponse(response))
      : new Promise<Response>(() => {})
  ) as typeof fetch;
});

/** The windowed list lists `windowed`; a list with no `since` lists `older` too. */
function mockWindowedRuns(windowed: CCPairRun[], older: CCPairRun) {
  const page = (items: CCPairRun[]): CCPairRunsResponse => ({
    items,
    total_items: items.length,
    kinds: ["indexing", "checks", "pruning"],
    status_counts: {
      running: 0,
      succeeded: items.length,
      failed: 0,
      canceled: 0,
    },
  });
  global.fetch = jest.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (!url.includes(`/cc-pair/${CC_PAIR_ID}/runs?`)) {
      return new Promise<Response>(() => {});
    }
    const params = new URL(url, "http://localhost").searchParams;
    const items = params.has("since") ? windowed : [older, ...windowed];
    return Promise.resolve(jsonResponse(page(items)));
  }) as typeof fetch;
}
/** The windowed list lists `windowed`; a list with no `since` pages through `allTime` by `page_num` and `page_size`. */
function mockPagedRuns(windowed: CCPairRun[], allTime: CCPairRun[]) {
  global.fetch = jest.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (!url.includes(`/cc-pair/${CC_PAIR_ID}/runs?`)) {
      return new Promise<Response>(() => {});
    }
    const params = new URL(url, "http://localhost").searchParams;
    const listed = params.has("since") ? windowed : allTime;
    const pageNum = Number(params.get("page_num"));
    const pageSize = Number(params.get("page_size"));
    const body: CCPairRunsResponse = {
      items: listed.slice(pageNum * pageSize, (pageNum + 1) * pageSize),
      total_items: listed.length,
      kinds: ["indexing"],
      status_counts: {
        running: 0,
        succeeded: listed.length,
        failed: 0,
        canceled: 0,
      },
    };
    return Promise.resolve(jsonResponse(body));
  }) as typeof fetch;
}
afterEach(() => {
  global.fetch = realFetch;
});

async function renderRuns(openRun: RunRef | null) {
  const view = render(
    <RunsCard ccPairId={CC_PAIR_ID} canOperate openRun={openRun} />
  );
  await screen.findAllByText("indexed");
  return view;
}

describe("RunsCard openRun", () => {
  it("opens the pointed index run's stage details once it lists", async () => {
    await renderRuns({ id: 2, kind: "indexing" });
    expect(
      await screen.findByRole("button", { name: CLOSE_STAGES })
    ).toBeInTheDocument();
  });

  it("opens a checks run with shown results at its check results", async () => {
    await renderRuns({ id: 9, kind: "checks" });
    expect(
      await screen.findByRole("button", { name: CLOSE_CHECKS })
    ).toBeInTheDocument();
  });

  it("reopens the same run for a new request after the admin closed it", async () => {
    const user = setupUser();
    const { rerender } = await renderRuns({ id: 1, kind: "indexing" });
    await user.click(await screen.findByRole("button", { name: CLOSE_STAGES }));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: CLOSE_STAGES })).toBeNull()
    );

    rerender(
      <RunsCard
        ccPairId={CC_PAIR_ID}
        canOperate
        openRun={{ id: 1, kind: "indexing" }}
      />
    );
    expect(
      await screen.findByRole("button", { name: CLOSE_STAGES })
    ).toBeInTheDocument();
  });

  it("opens nothing for a prune run, whose id an index run shares", async () => {
    await renderRuns({ id: 1, kind: "pruning" });
    // A pass of the open effect after the list settles.
    await screen.findAllByText("indexed");
    expect(screen.queryByRole("button", { name: CLOSE_STAGES })).toBeNull();
    expect(screen.queryByRole("button", { name: CLOSE_CHECKS })).toBeNull();
  });

  it("widens to the run's kind over all time when the window misses it", async () => {
    mockWindowedRuns([indexRun(1)], indexRun(40));
    await renderRuns({ id: 40, kind: "indexing" });
    expect(
      await screen.findByRole("button", { name: CLOSE_STAGES })
    ).toBeInTheDocument();
    const urls = (global.fetch as jest.Mock).mock.calls.map((call) =>
      String(call[0])
    );
    expect(
      urls.some(
        (url) => url.includes("kinds=indexing") && !url.includes("since=")
      )
    ).toBe(true);
  });

  it("pages back through the run's kind when newer runs push it off the first page", async () => {
    const allTime = Array.from({ length: 25 }, (_, index) =>
      indexRun(index + 1)
    );
    mockPagedRuns([indexRun(1)], allTime);
    await renderRuns({ id: 23, kind: "indexing" });
    expect(
      await screen.findByRole("button", { name: CLOSE_STAGES })
    ).toBeInTheDocument();
    const urls = (global.fetch as jest.Mock).mock.calls.map((call) =>
      String(call[0])
    );
    expect(
      urls.some(
        (url) =>
          url.includes("kinds=indexing") &&
          url.includes("page_num=2") &&
          !url.includes("since=")
      )
    ).toBe(true);
  });

  it("stops paging once the kind's runs are exhausted without the run", async () => {
    const allTime = Array.from({ length: 15 }, (_, index) =>
      indexRun(index + 1)
    );
    mockPagedRuns([indexRun(1)], allTime);
    await renderRuns({ id: 99, kind: "indexing" });
    const pagesAsked = () =>
      (global.fetch as jest.Mock).mock.calls
        .map((call) => String(call[0]))
        .filter((url) => !url.includes("since="));
    await waitFor(() =>
      expect(pagesAsked().some((url) => url.includes("page_num=1"))).toBe(true)
    );
    // A pass of the open effect after the last page settles.
    await screen.findAllByText("indexed");
    expect(pagesAsked().some((url) => url.includes("page_num=2"))).toBe(false);
    expect(screen.queryByRole("button", { name: CLOSE_STAGES })).toBeNull();
  });

  it("lists a prune run the window misses without opening it", async () => {
    mockWindowedRuns([indexRun(1)], PRUNE_RUN);
    await renderRuns({ id: 1, kind: "pruning" });
    await waitFor(() => {
      const urls = (global.fetch as jest.Mock).mock.calls.map((call) =>
        String(call[0])
      );
      expect(
        urls.some(
          (url) => url.includes("kinds=pruning") && !url.includes("since=")
        )
      ).toBe(true);
    });
    // The picked type filter and the listed run.
    await waitFor(() =>
      expect(
        screen.getAllByText(copy("admin.connector.runs.kinds.pruning"))
      ).toHaveLength(2)
    );
    expect(screen.queryByRole("button", { name: CLOSE_STAGES })).toBeNull();
  });
});

describe("RunsCard past runs row", () => {
  const PAST = [indexRun(1), indexRun(2), indexRun(3)];

  async function renderEmptyWindow() {
    mockPagedRuns([], PAST);
    render(<RunsCard ccPairId={CC_PAIR_ID} canOperate openRun={null} />);
    return screen.findByText("3 Past Runs");
  }

  it("names the row's control with the past run count", async () => {
    await renderEmptyWindow();
    expect(
      screen.getByRole("button", { name: /3 Past Runs/ })
    ).toBeInTheDocument();
  });

  it("widens the list to all time on a click on the row title", async () => {
    const user = setupUser();
    await user.click(await renderEmptyWindow());
    expect(await screen.findAllByText("indexed")).toHaveLength(PAST.length);
  });
});
