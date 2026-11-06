/** The activity panel's links to the page around it: the chart's hover and focus (widening a span that hides the failure), the empty panel's Past Activities, Resolve All on a level the batch routes cannot narrow to, the Connectors menu while it loads, pages and fails, an index chip's label, Resolve on running runs, and a searched superseded run. */
import { useState } from "react";
import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import userEvent from "@testing-library/user-event";
import {
  useActivityChartLinks,
  type ActivityScope,
} from "@/lib/connectors/ccPair/hooks";
import ActivityPanel from "@/views/admin/connectors/ConnectorDetailPage/ActivityPanel";
import type { SliceRange } from "@/views/admin/connectors/ConnectorDetailPage/ThroughputChart";
import {
  SALES_DRIVE,
  SUPPORT_INBOX,
  cardFor,
  cardKeys,
  indexRun,
  type FeedPair,
  installActivityFeed,
  permSyncRun,
  minutesAgo,
  restoreFetch,
} from "@tests/setup/activityFeedTestUtils";

async function pickLevel(
  user: ReturnType<typeof userEvent.setup>,
  name: string
) {
  await user.click(screen.getByRole("button", { name: "Errors" }));
  await user.click(await screen.findByRole("option", { name }));
}

const PAIR: ActivityScope = {
  ccPairId: SALES_DRIVE.id,
  canResolve: true,
  canResolveRuns: true,
};

const FAILED = indexRun({
  id: 101,
  status: "failed",
  minutesAgo: 5,
  errorMsg: "Service unavailable.",
});
const RUNNING_ERRORS = indexRun({
  id: 203,
  status: "in_progress",
  minutesAgo: 2,
  openErrors: 4,
});

beforeEach(() => {
  Element.prototype.scrollIntoView = jest.fn();
  window.sessionStorage.clear();
});
afterEach(() => restoreFetch());

describe("useActivityChartLinks", () => {
  it("hands a hovered line's runs and a focused failure to the panel, and a hovered card to the chart", () => {
    const { result } = renderHook(() => useActivityChartLinks());

    act(() => {
      result.current.chart.onHoverLine?.({
        kind: "failed",
        attemptIds: [7, 8],
      });
      result.current.chart.onFocusAttempt?.(7);
      result.current.panel.onHoverAttempt(9);
    });
    expect(result.current.panel.outlinedAttemptIds).toEqual([7, 8]);
    expect(result.current.panel.focusAttemptId).toBe(7);
    expect(result.current.chart.hoveredAttemptId).toBe(9);

    act(() => result.current.chart.onHoverLine?.(null));
    expect(result.current.panel.outlinedAttemptIds).toEqual([]);
  });

  it("runs the page's focus side effect, and leaving a card ends the focus", () => {
    const onFocusAttempt = jest.fn();
    const { result } = renderHook(() =>
      useActivityChartLinks({ onFocusAttempt })
    );

    act(() => result.current.chart.onFocusAttempt?.(7));
    expect(onFocusAttempt).toHaveBeenCalledWith(7);
    expect(result.current.panel.focusAttemptId).toBe(7);

    act(() => result.current.panel.onHoverAttempt(7));
    expect(result.current.panel.focusAttemptId).toBe(7);
    act(() => result.current.panel.onHoverAttempt(null));
    expect(result.current.panel.focusAttemptId).toBeNull();
    expect(result.current.chart.hoveredAttemptId).toBeNull();
  });
});

describe("Past Activities", () => {
  it("widens the time filter when clicked", async () => {
    const old = indexRun({
      id: 801,
      status: "failed",
      minutesAgo: 3 * 24 * 60,
      errorMsg: "Old outage.",
    });
    installActivityFeed([old]);
    const onClearRange = jest.fn();
    const user = userEvent.setup();
    render(
      <ActivityPanel
        scope={PAIR}
        title="Activities"
        range={{ since: minutesAgo(60), until: minutesAgo(-1) }}
        onClearRange={onClearRange}
      />
    );

    await user.click(await screen.findByText("Past Activities"));
    expect(onClearRange).toHaveBeenCalledTimes(1);
  });
});

describe("Resolve All on the Running level", () => {
  it("is hidden, since the batch routes cannot narrow to running runs", async () => {
    installActivityFeed([FAILED, RUNNING_ERRORS]);
    const user = userEvent.setup();
    render(<ActivityPanel scope={PAIR} title="Activities" />);
    const resolveAll = await screen.findByRole("button", {
      name: "Resolve All",
    });
    await waitFor(() => expect(resolveAll).toBeEnabled());

    await user.click(screen.getByRole("button", { name: "Show Filters" }));
    await user.click(screen.getByRole("button", { name: "Errors" }));
    await user.click(await screen.findByRole("option", { name: "Running" }));

    await waitFor(() => expect(cardFor(FAILED)).toBeNull());
    expect(cardFor(RUNNING_ERRORS)).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Resolve All" })).toBeNull();
  });
});

describe("Past Activities on the Running level", () => {
  it("counts only running runs with errors, so an older finished run with errors offers nothing", async () => {
    const olderErrors = indexRun({
      id: 802,
      status: "completed_with_errors",
      minutesAgo: 3 * 24 * 60,
      openErrors: 2,
    });
    installActivityFeed([olderErrors]);
    const user = userEvent.setup();
    render(
      <ActivityPanel
        scope={PAIR}
        title="Activities"
        range={{ since: minutesAgo(60), until: minutesAgo(-1) }}
        onClearRange={jest.fn()}
      />
    );
    // The Errors level lists it, so Past Activities offers it there.
    expect(await screen.findByText("Past Activities")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show Filters" }));
    await pickLevel(user, "Running");
    await user.click(screen.getByRole("button", { name: "Hide Filters" }));

    await screen.findByText("No recent activity");
    await waitFor(() =>
      expect(screen.queryByText("Past Activities")).toBeNull()
    );
  });
});

describe("Chart focus on a hidden card", () => {
  it("brings back a level that lists the failure, and pages to it", async () => {
    const failures = Array.from({ length: 25 }, (_, index) =>
      indexRun({
        id: 300 + index,
        status: "failed",
        minutesAgo: 10 + index,
        errorMsg: `Outage ${index}.`,
      })
    );
    const target = failures[failures.length - 1]!;
    installActivityFeed(failures);
    const user = userEvent.setup();
    const { rerender } = render(
      <ActivityPanel scope={PAIR} title="Activities" />
    );
    await waitFor(() => expect(cardFor(failures[0]!)).not.toBeNull());
    expect(cardFor(target)).toBeNull();

    await user.click(screen.getByRole("button", { name: "Show Filters" }));
    await pickLevel(user, "Success");
    await waitFor(() => expect(cardFor(failures[0]!)).toBeNull());

    rerender(
      <ActivityPanel
        scope={PAIR}
        title="Activities"
        focusAttemptId={target.run.attempt.id}
      />
    );

    await waitFor(() => expect(cardFor(target)).not.toBeNull());
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  });
});

describe("Chart focus on a failure outside the chart's span", () => {
  interface SpannedPanelProps {
    focusAttemptId: number | null;
    onClearRange: () => void;
  }
  /** The page's span state, which the panel's onClearRange drops. */
  function SpannedPanel({ focusAttemptId, onClearRange }: SpannedPanelProps) {
    const [range, setRange] = useState<SliceRange | null>({
      since: minutesAgo(60),
      until: minutesAgo(-1),
    });
    return (
      <ActivityPanel
        scope={PAIR}
        title="Activities"
        range={range}
        onClearRange={() => {
          onClearRange();
          setRange(null);
        }}
        focusAttemptId={focusAttemptId}
      />
    );
  }
  const old = indexRun({
    id: 803,
    status: "failed",
    minutesAgo: 3 * 24 * 60,
    errorMsg: "Old outage.",
  });

  it("widens the span to list the failure", async () => {
    installActivityFeed([FAILED, old]);
    const onClearRange = jest.fn();
    const { rerender } = render(
      <SpannedPanel focusAttemptId={null} onClearRange={onClearRange} />
    );
    await waitFor(() => expect(cardFor(FAILED)).not.toBeNull());
    expect(cardFor(old)).toBeNull();

    rerender(
      <SpannedPanel
        focusAttemptId={old.run.attempt.id}
        onClearRange={onClearRange}
      />
    );

    await waitFor(() => expect(cardFor(old)).not.toBeNull());
    expect(onClearRange).toHaveBeenCalledTimes(1);
  });

  it("keeps a span that already lists the failure", async () => {
    installActivityFeed([FAILED, old]);
    const onClearRange = jest.fn();
    const { rerender } = render(
      <SpannedPanel focusAttemptId={null} onClearRange={onClearRange} />
    );
    await waitFor(() => expect(cardFor(FAILED)).not.toBeNull());

    rerender(
      <SpannedPanel
        focusAttemptId={FAILED.run.attempt.id}
        onClearRange={onClearRange}
      />
    );

    await waitFor(() =>
      expect(Element.prototype.scrollIntoView).toHaveBeenCalled()
    );
    expect(cardFor(old)).toBeNull();
    expect(onClearRange).not.toHaveBeenCalled();
  });
});

describe("Connectors filter", () => {
  it("says it is loading while a typed search's page is on its way, then lists the matches", async () => {
    installActivityFeed([FAILED]);
    const feedFetch = global.fetch;
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    global.fetch = jest.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const raw = typeof input === "string" ? input : input.toString();
        if (
          raw.includes("/index-monitoring/connectors") &&
          raw.includes("q=")
        ) {
          await held;
        }
        return feedFetch(input, init);
      }
    ) as typeof fetch;
    const user = userEvent.setup();
    render(<ActivityPanel scope="fleet" title="Activities" />);

    await user.click(
      await screen.findByRole("button", { name: "Show Filters" })
    );
    await user.click(screen.getByRole("button", { name: "Connectors" }));
    expect(await screen.findByText(SUPPORT_INBOX.name)).toBeInTheDocument();

    await user.type(
      screen.getByPlaceholderText("Search connectors…"),
      SALES_DRIVE.name.slice(0, 4)
    );
    expect(await screen.findByText("Loading connectors…")).toBeInTheDocument();

    act(() => release());
    await waitFor(() =>
      expect(screen.queryByText("Loading connectors…")).toBeNull()
    );
    expect(screen.getByText(SALES_DRIVE.name)).toBeInTheDocument();
  });
});

describe("Connectors filter pages and failures", () => {
  /** Serves the connectors route a page at a time over the installed feed, which lists every match at once. */
  function pageConnectors(fail: () => boolean) {
    const feedFetch = global.fetch;
    global.fetch = jest.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const raw = typeof input === "string" ? input : input.toString();
        if (!raw.includes("/index-monitoring/connectors")) {
          return feedFetch(input, init);
        }
        if (fail()) return new Response("{}", { status: 500 });
        const params = new URL(raw, "http://localhost").searchParams;
        const pageNum = Number(params.get("page_num"));
        const pageSize = Number(params.get("page_size"));
        const all = await (await feedFetch(input, init)).json();
        return new Response(
          JSON.stringify({
            ...all,
            items: all.items.slice(
              pageNum * pageSize,
              (pageNum + 1) * pageSize
            ),
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
    ) as typeof fetch;
  }

  it("loads the next page of connectors when the list scrolls to its end", async () => {
    const many: FeedPair[] = Array.from({ length: 150 }, (_, index) => ({
      ...SUPPORT_INBOX,
      id: 1000 + index,
      name: `Pair ${String(index).padStart(3, "0")}`,
    }));
    installActivityFeed([FAILED], [SALES_DRIVE, ...many]);
    pageConnectors(() => false);
    const user = userEvent.setup();
    render(<ActivityPanel scope="fleet" title="Activities" />);

    await user.click(
      await screen.findByRole("button", { name: "Show Filters" })
    );
    await user.click(screen.getByRole("button", { name: "Connectors" }));
    expect(await screen.findByText("Pair 000")).toBeInTheDocument();
    expect(screen.queryByText("Pair 140")).toBeNull();

    fireEvent.scroll(screen.getByRole("listbox"));

    expect(await screen.findByText("Pair 140")).toBeInTheDocument();
  });

  it("shows a failed load as an error with Retry, not as no connectors", async () => {
    installActivityFeed([FAILED]);
    let failing = true;
    pageConnectors(() => failing);
    const user = userEvent.setup();
    render(<ActivityPanel scope="fleet" title="Activities" />);

    await user.click(
      await screen.findByRole("button", { name: "Show Filters" })
    );
    await user.click(screen.getByRole("button", { name: "Connectors" }));
    expect(
      await screen.findByText("Couldn't load connectors.")
    ).toBeInTheDocument();
    expect(screen.queryByText(SUPPORT_INBOX.name)).toBeNull();

    failing = false;
    await user.click(screen.getByText("Retry"));

    expect(await screen.findByText(SUPPORT_INBOX.name)).toBeInTheDocument();
    expect(screen.queryByText("Couldn't load connectors.")).toBeNull();
  });
});

describe("Index chip label", () => {
  it("counts items, not docs, when an open error covers a whole source", async () => {
    const sourceError = indexRun({
      id: 401,
      status: "failed",
      minutesAgo: 3,
      errorMsg: "Space unavailable.",
      openErrors: 3,
      openDocErrors: 1,
    });
    installActivityFeed([sourceError]);
    render(<ActivityPanel scope={PAIR} title="Activities" />);

    await waitFor(() => expect(cardFor(sourceError)).not.toBeNull());
    const card = cardFor(sourceError)!;
    expect(within(card).getByText("3 items failed")).toBeInTheDocument();
    expect(within(card).queryByText(/docs? failed/)).toBeNull();
  });
});

describe("Resolve on a running run", () => {
  it("shows on a running index run with errors, not on a running permission sync the server would refuse", async () => {
    const runningSync = permSyncRun({
      id: 602,
      status: "in_progress",
      minutesAgo: 1,
      docsWithPermissionErrors: 3,
    });
    installActivityFeed([RUNNING_ERRORS, runningSync]);
    render(<ActivityPanel scope={PAIR} title="Activities" />);

    await waitFor(() => expect(cardFor(runningSync)).not.toBeNull());
    await waitFor(() => expect(cardFor(RUNNING_ERRORS)).not.toBeNull());
    expect(
      within(cardFor(RUNNING_ERRORS)!).getByRole("button", { name: "Resolve" })
    ).toBeInTheDocument();
    expect(
      within(cardFor(runningSync)!).queryByRole("button", { name: "Resolve" })
    ).toBeNull();
  });
});

describe("A searched superseded failure with Resolved on", () => {
  it("lists once, under Resolved, though the search finds it under Failures too", async () => {
    const superseded = indexRun({
      id: 501,
      status: "failed",
      minutesAgo: 40,
      errorMsg: "Quota exceeded.",
      superseded: true,
    });
    installActivityFeed([superseded]);
    const user = userEvent.setup();
    render(<ActivityPanel scope={PAIR} title="Activities" />);

    await user.click(
      await screen.findByRole("button", { name: "Show Filters" })
    );
    await user.click(screen.getByRole("button", { name: /^Resolved$/ }));
    await waitFor(() => expect(cardFor(superseded)).not.toBeNull());
    await user.type(
      screen.getByPlaceholderText("Search activity history…"),
      "Quota"
    );

    await waitFor(() =>
      expect(
        (global.fetch as jest.Mock).mock.calls.some(([url]) =>
          String(url).includes("q=Quota")
        )
      ).toBe(true)
    );
    await waitFor(() => expect(cardFor(superseded)).not.toBeNull());
    expect(cardKeys().filter((key) => key === "indexing-501")).toHaveLength(1);
    const resolved = screen
      .getAllByTestId("activity-section")
      .find((section) => within(section).queryByText("Resolved") !== null);
    expect(within(resolved!).getAllByTestId("activity-card")).toHaveLength(1);
  });

  it("keeps Show more when every loaded failure repeats under Resolved, so an older open one stays reachable", async () => {
    const supersededRuns = Array.from({ length: 20 }, (_, index) =>
      indexRun({
        id: 520 + index,
        status: "failed",
        minutesAgo: 10 + index,
        errorMsg: "Quota exceeded.",
        superseded: true,
      })
    );
    const olderOpen = indexRun({
      id: 519,
      status: "failed",
      minutesAgo: 90,
      errorMsg: "Quota exceeded again.",
    });
    installActivityFeed([...supersededRuns, olderOpen]);
    const user = userEvent.setup();
    render(<ActivityPanel scope={PAIR} title="Activities" />);

    await user.click(
      await screen.findByRole("button", { name: "Show Filters" })
    );
    await user.click(screen.getByRole("button", { name: /^Resolved$/ }));
    await user.type(
      screen.getByPlaceholderText("Search activity history…"),
      "Quota"
    );
    await waitFor(() =>
      expect(
        (global.fetch as jest.Mock).mock.calls.some(([url]) =>
          String(url).includes("q=Quota")
        )
      ).toBe(true)
    );
    await waitFor(() => expect(cardFor(supersededRuns[0]!)).not.toBeNull());
    expect(cardFor(olderOpen)).toBeNull();

    await user.click(await screen.findByRole("button", { name: "Show more" }));
    await waitFor(() => expect(cardFor(olderOpen)).not.toBeNull());
  });
});
