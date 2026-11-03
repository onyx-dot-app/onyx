/** The throughput chart: local-time labels, a bin count from its width, a y floor of 100, three status lines per bar from each slice's runs, and a brush that narrows the activity feed. */
import { useState } from "react";
import { createFormatter } from "next-intl";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { render, setupUser } from "@tests/setup/test-utils";
import type { CCPairThroughputResponse } from "@/lib/connectors/types/ccPair";
import ThroughputChart, {
  ThroughputBars,
  binsForWidth,
  formatSliceRange,
  formatTickLabel,
  yScaleMax,
  type SliceRange,
} from "@/views/admin/connectors/ConnectorDetailPage/ThroughputChart";
import {
  FIXTURE_BINS,
  installChartLayout,
  isFaded,
  resetChartLayout,
  setChartWidth,
  sliceEnd,
  sliceStart,
  throughputFixture,
  usesToken,
} from "@tests/setup/throughputChartTestUtils";

const originalFetch = global.fetch;

afterEach(() => {
  resetChartLayout();
  global.fetch = originalFetch;
  jest.restoreAllMocks();
});

const LOCAL_ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;
// next-intl formats in the server's zone. Any zone far from the local one shows a missing override.
const SERVER_ZONE =
  LOCAL_ZONE === "Pacific/Kiritimati" ? "Etc/GMT+12" : "Pacific/Kiritimati";
const serverFormat = createFormatter({ locale: "en", timeZone: SERVER_ZONE });

describe("chart labels", () => {
  // Noon UTC is the next day in Kiritimati, so a day label shows the zone too.
  const instant = Date.UTC(2026, 9, 21, 12, 0);

  it("labels a time tick in the browser's zone", () => {
    expect(formatTickLabel(serverFormat, instant, 10)).toBe(
      new Intl.DateTimeFormat("en", {
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      }).format(instant)
    );
  });

  it("labels a day tick with the browser's date", () => {
    expect(formatTickLabel(serverFormat, instant, 1440)).toBe(
      new Intl.DateTimeFormat("en", { month: "short", day: "numeric" }).format(
        instant
      )
    );
  });

  it("shows a slice's span in the browser's zone", () => {
    const from = new Date(instant);
    const to = new Date(instant + 20 * 60_000);
    expect(formatSliceRange(serverFormat, from, to)).toBe(
      new Intl.DateTimeFormat("en", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      }).formatRange(from, to)
    );
  });
});

describe("AC-1: bins from the chart's width", () => {
  it.each([
    [2000, 72],
    [685, 72],
    [684, 72],
    [683, 60],
    [600, 60],
    [570, 60],
    [569, 48],
    [472, 48],
    [456, 48],
    [455, 36],
    [408, 36],
    [342, 36],
    [341, 30],
    [285, 30],
    [284, 24],
    [228, 24],
    [227, 18],
    [171, 18],
    [170, 12],
    [114, 12],
    [60, 12],
    [0, 12],
  ])("AC-1: %i px wide draws %i bins", (width, bins) => {
    expect(binsForWidth(width)).toBe(bins);
  });

  const CC_PAIR_ID = 7;

  function throughputCalls(fetchMock: jest.Mock): URLSearchParams[] {
    return fetchMock.mock.calls
      .map(([input]) => String(input))
      .filter((url) =>
        url.includes(`/api/manage/admin/cc-pair/${CC_PAIR_ID}/throughput`)
      )
      .map((url) => new URL(url, "http://localhost").searchParams);
  }

  function mockFetch(): jest.Mock {
    const fetchMock = jest.fn(
      async () =>
        new Response(JSON.stringify(throughputFixture()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
    );
    global.fetch = fetchMock as unknown as typeof fetch;
    return fetchMock;
  }

  it.each([
    [420, "-420"],
    [-330, "330"],
  ])(
    "AC-1: asks for the measured bin count and the browser's clock (getTimezoneOffset %i)",
    async (browserOffset, sent) => {
      jest
        .spyOn(Date.prototype, "getTimezoneOffset")
        .mockReturnValue(browserOffset);
      installChartLayout(600);
      const fetchMock = mockFetch();

      render(<ThroughputChart ccPairId={CC_PAIR_ID} range="24h" />);

      await waitFor(() => expect(throughputCalls(fetchMock)).not.toEqual([]));
      for (const params of throughputCalls(fetchMock)) {
        expect(params.get("window")).toBe("24h");
        expect(params.get("bins")).toBe("60");
        expect(params.get("tz_offset_minutes")).toBe(sent);
      }
    }
  );

  it("AC-1: a resize that changes the bin count refetches once", async () => {
    jest.spyOn(Date.prototype, "getTimezoneOffset").mockReturnValue(0);
    installChartLayout(600);
    const fetchMock = mockFetch();
    render(<ThroughputChart ccPairId={CC_PAIR_ID} range="24h" />);
    await waitFor(() =>
      expect(
        throughputCalls(fetchMock).map((params) => params.get("bins"))
      ).toContain("60")
    );

    // 590 px keeps 60 bins, 472 px drops to 48.
    setChartWidth(590);
    setChartWidth(472);

    await waitFor(
      () =>
        expect(
          throughputCalls(fetchMock).map((params) => params.get("bins"))
        ).toContain("48"),
      { timeout: 3000 }
    );
    const bins = throughputCalls(fetchMock).map((params) => params.get("bins"));
    expect(bins.filter((count) => count === "60")).toHaveLength(1);
    expect(bins.filter((count) => count === "48")).toHaveLength(1);
  });
});

describe("AC-2: y scale", () => {
  it.each([
    [[], 100],
    [[0, 0, 0], 100],
    [[50, 3], 100],
    [[100], 100],
    [[101, 3], 101],
    [[12, 250, 40], 250],
  ])("AC-2: bins %j reach up to %i", (docs, max) => {
    expect(yScaleMax(docs)).toBe(max);
  });
});

function statusLines(container: HTMLElement): HTMLElement[] {
  return Array.from(
    container.querySelectorAll<HTMLElement>('[data-testid="chart-status-line"]')
  );
}

function bars(container: HTMLElement): HTMLElement[] {
  return Array.from(
    container.querySelectorAll<HTMLElement>('[data-testid="chart-bar"]')
  );
}

const RUNNING_TOKEN = "chart-sequential-mass-02-blue";
const FAILED_TOKEN = "chart-diverging-neg-10-red";
const RESOLVED_TOKEN = "chart-diverging-neg-02-red";
const BRUSH_TOKEN = "chart-category-blue-1-05";

describe("AC-3: status lines", () => {
  const data = throughputFixture({
    docs: { 2: 40, 5: 12 },
    runs: {
      2: [{ attempt_id: 201, status: "in_progress", resolved: false }],
      5: [
        { attempt_id: 501, status: "failed", resolved: false },
        { attempt_id: 502, status: "failed", resolved: true },
      ],
      7: [{ attempt_id: 701, status: "success", resolved: false }],
      8: [{ attempt_id: 801, status: "canceled", resolved: false }],
    },
  });

  it("AC-3: draws a running, a failed and a resolved failure line, and none for slices without such runs", () => {
    installChartLayout(600);
    const { container } = render(<ThroughputBars data={data} range="24h" />);

    const lines = statusLines(container);
    expect(lines).toHaveLength(3);
    expect(lines.filter((line) => usesToken(line, RUNNING_TOKEN))).toHaveLength(
      1
    );
    expect(lines.filter((line) => usesToken(line, FAILED_TOKEN))).toHaveLength(
      1
    );
    expect(
      lines.filter((line) => usesToken(line, RESOLVED_TOKEN))
    ).toHaveLength(1);
  });

  it("AC-3: draws no line for an all-zero window and still draws every bar", () => {
    installChartLayout(600);
    const { container } = render(
      <ThroughputBars data={throughputFixture()} range="24h" />
    );

    expect(statusLines(container)).toHaveLength(0);
    expect(bars(container)).toHaveLength(FIXTURE_BINS);
  });

  it("AC-3: a bar is a button labeled with its document count", () => {
    installChartLayout(600);
    const { container } = render(<ThroughputBars data={data} range="24h" />);

    const bar = bars(container)[2]!;
    expect(bar).toHaveAttribute("role", "button");
    expect(bar.getAttribute("aria-label")).toContain("40 documents");
  });

  it("AC-3: hovering a failure line shows the slice's failures and errors and its time range", async () => {
    installChartLayout(600);
    const counted = throughputFixture({
      runs: {
        5: [
          { attempt_id: 501, status: "failed", resolved: false },
          { attempt_id: 503, status: "failed", resolved: false },
          { attempt_id: 504, status: "completed_with_errors", resolved: false },
          { attempt_id: 505, status: "completed_with_errors", resolved: false },
          { attempt_id: 506, status: "completed_with_errors", resolved: false },
        ],
      },
    });
    const user = setupUser();
    const { container } = render(<ThroughputBars data={counted} range="24h" />);
    const failed = statusLines(container).find((line) =>
      usesToken(line, FAILED_TOKEN)
    );
    expect(failed).toBeDefined();
    expect(document.body.textContent).not.toContain("2 failures, 3 errors");

    await user.hover(failed!);

    const range = formatSliceRange(
      createFormatter({ locale: "en", timeZone: LOCAL_ZONE }),
      new Date(sliceStart(5)),
      new Date(sliceEnd(5))
    );
    await waitFor(
      () => {
        expect(document.body.textContent).toContain("2 failures, 3 errors");
        expect(document.body.textContent).toContain(range);
      },
      { timeout: 3000 }
    );
  });
});

/** Holds the brush the way a page does, so a second click on the same bar can clear it. */
function BrushHarness({
  data,
  onRangeSelect,
}: {
  data: CCPairThroughputResponse;
  onRangeSelect: (range: SliceRange | null) => void;
}) {
  const [selection, setSelection] = useState<SliceRange | null>(null);
  return (
    <ThroughputBars
      data={data}
      range="24h"
      selection={selection}
      onRangeSelect={(range: SliceRange | null) => {
        onRangeSelect(range);
        setSelection(range);
      }}
    />
  );
}

function expectRange(
  range: SliceRange | null | undefined,
  from: number,
  to: number
) {
  expect(range).not.toBeNull();
  expect(range).toBeDefined();
  expect(Date.parse(range!.since)).toBe(from);
  expect(Date.parse(range!.until)).toBe(to);
}

// One 10 px slot per bin at 600 px and 60 bins.
function slotCenter(index: number): number {
  return index * 10 + 5;
}

function pointer(kind: "down" | "move" | "up", target: Element, index: number) {
  const init = {
    clientX: slotCenter(index),
    clientY: 60,
    pointerId: 1,
    pointerType: "mouse",
    isPrimary: true,
    button: 0,
    buttons: kind === "up" ? 0 : 1,
    bubbles: true,
  };
  if (kind === "down") {
    fireEvent.pointerDown(target, init);
    fireEvent.mouseDown(target, init);
  } else if (kind === "move") {
    fireEvent.pointerMove(target, init);
    fireEvent.mouseMove(target, init);
  } else {
    fireEvent.pointerUp(target, init);
    fireEvent.mouseUp(target, init);
  }
}

/** A click as a browser sends it, at the bar's slot so the bin can come from the target or from the pointer's x. */
function clickBar(target: Element, index: number) {
  pointer("down", target, index);
  pointer("up", target, index);
  fireEvent.click(target, { clientX: slotCenter(index), clientY: 60 });
}

describe("AC-5: brush time filter", () => {
  const data = throughputFixture({ docs: { 1: 5, 2: 8, 3: 13, 4: 21, 9: 3 } });

  it("AC-5: a click on a bar selects its slice and a second click clears it", () => {
    installChartLayout(600);
    const onRangeSelect = jest.fn();
    const { container } = render(
      <BrushHarness data={data} onRangeSelect={onRangeSelect} />
    );
    expect(bars(container)).toHaveLength(FIXTURE_BINS);

    clickBar(bars(container)[3]!, 3);
    expectRange(
      onRangeSelect.mock.calls.at(-1)?.[0],
      sliceStart(3),
      sliceEnd(3)
    );

    clickBar(bars(container)[3]!, 3);
    expect(onRangeSelect).toHaveBeenLastCalledWith(null);
  });

  it("AC-5: a drag across bars selects the slices it covered", () => {
    installChartLayout(600);
    const onRangeSelect = jest.fn();
    const { container } = render(
      <BrushHarness data={data} onRangeSelect={onRangeSelect} />
    );
    expect(bars(container)).toHaveLength(FIXTURE_BINS);

    pointer("down", bars(container)[2]!, 2);
    pointer("move", bars(container)[3]!, 3);
    pointer("move", bars(container)[4]!, 4);
    pointer("up", bars(container)[4]!, 4);

    expectRange(
      onRangeSelect.mock.calls.at(-1)?.[0],
      sliceStart(2),
      sliceEnd(4)
    );
  });

  it("AC-5: a selection keeps the whole window in view, draws the brush and fades the other bars", () => {
    installChartLayout(600);
    const selection = {
      since: new Date(sliceStart(2)).toISOString(),
      until: new Date(sliceEnd(4)).toISOString(),
    };
    const { container, rerender } = render(
      <ThroughputBars data={data} range="24h" selection={null} />
    );
    expect(container.innerHTML).not.toContain(BRUSH_TOKEN);

    rerender(<ThroughputBars data={data} range="24h" selection={selection} />);

    // A selection fades the bars outside it and still draws every bin.
    const drawn = bars(container);
    expect(drawn).toHaveLength(FIXTURE_BINS);
    expect(container.innerHTML).toContain(BRUSH_TOKEN);
    for (const index of [2, 3, 4]) {
      expect(isFaded(drawn[index]!, container)).toBe(false);
    }
    for (const index of [0, 1, 5, 9, FIXTURE_BINS - 1]) {
      expect(isFaded(drawn[index]!, container)).toBe(true);
    }
  });
});

describe("flat fallback", () => {
  it("draws a response without slices as equal bars with no status lines", () => {
    installChartLayout(600);
    const { slices: _slices, ...flat } = throughputFixture({
      docs: { 0: 7, 59: 9 },
    });

    const { container } = render(<ThroughputBars data={flat} range="24h" />);

    expect(bars(container)).toHaveLength(FIXTURE_BINS);
    expect(bars(container)[0]?.getAttribute("aria-label")).toContain(
      "7 documents"
    );
    expect(statusLines(container)).toHaveLength(0);
  });
});

/** Gives every tooltip card, and any other element sized to its content, 150 px inside the 600 px chart. */
function sizeContentBoxes() {
  const measured = Element.prototype.getBoundingClientRect;
  Element.prototype.getBoundingClientRect = function (this: Element) {
    const box = measured.call(this);
    return this.classList.contains("w-max")
      ? ({ ...box, width: 150, right: box.left + 150 } as DOMRect)
      : box;
  };
}

/** The left edge the browser resolves from the card's clamped inline start inside a parent this wide. */
function resolvedStart(element: HTMLElement, parentWidth: number): number {
  const match =
    /clamp\(0px, calc\(([\d.]+)% - ([\d.]+)px\), calc\(100% - ([\d.]+)px\)\)/.exec(
      element.style.insetInlineStart
    );
  if (match === null) {
    throw new Error(`unclamped start: ${element.style.insetInlineStart}`);
  }
  const [at, half, width] = match.slice(1).map(Number) as [
    number,
    number,
    number,
  ];
  return Math.min(
    Math.max(0, (at / 100) * parentWidth - half),
    parentWidth - width
  );
}

describe("tooltips and keyboard", () => {
  const data = throughputFixture({ docs: { 0: 7, 1: 4, 30: 12, 59: 9 } });

  it.each([
    [0, "7 documents", 0],
    [30, "12 documents", 230],
    [59, "9 documents", 450],
  ])("keeps bar %i's tooltip inside the chart", async (index, title, start) => {
    installChartLayout(600);
    sizeContentBoxes();
    const user = setupUser();
    const { container } = render(<ThroughputBars data={data} range="24h" />);

    await user.hover(bars(container)[index]!);

    const card = (await screen.findByText(title)).closest<HTMLElement>(
      ".w-max"
    );
    expect(card).not.toBeNull();
    expect(resolvedStart(card!, 600)).toBe(start);
  });

  it("a keyboard user tabs to a bar, reads its tooltip, moves with the arrows and picks it with Enter", async () => {
    installChartLayout(600);
    const onRangeSelect = jest.fn();
    const user = setupUser();
    const { container } = render(
      <ThroughputBars data={data} range="24h" onRangeSelect={onRangeSelect} />
    );

    await user.tab();
    expect(bars(container)[0]).toHaveFocus();
    expect(document.body.textContent).toContain("7 documents");

    await user.keyboard("{ArrowRight}");
    expect(bars(container)[1]).toHaveFocus();
    expect(bars(container)[1]).toHaveAttribute("tabindex", "0");
    expect(bars(container)[0]).toHaveAttribute("tabindex", "-1");
    expect(document.body.textContent).toContain("4 documents");
    expect(document.body.textContent).not.toContain("7 documents");

    await user.keyboard("{Enter}");
    expectRange(
      onRangeSelect.mock.calls.at(-1)?.[0],
      sliceStart(1),
      sliceEnd(1)
    );
  });

  it("a screen reader's bare click picks a bar, and a pointer click picks once", () => {
    installChartLayout(600);
    const onRangeSelect = jest.fn();
    const { container } = render(
      <ThroughputBars data={data} range="24h" onRangeSelect={onRangeSelect} />
    );

    fireEvent.click(bars(container)[2]!);
    expect(onRangeSelect).toHaveBeenCalledTimes(1);
    expectRange(onRangeSelect.mock.calls[0]?.[0], sliceStart(2), sliceEnd(2));

    clickBar(bars(container)[4]!, 4);
    expect(onRangeSelect).toHaveBeenCalledTimes(2);
    expectRange(onRangeSelect.mock.calls[1]?.[0], sliceStart(4), sliceEnd(4));
  });

  it("keeps one bar in the tab order when fewer bars replace the focused one", async () => {
    installChartLayout(600);
    const user = setupUser();
    const { container, rerender } = render(
      <ThroughputBars data={data} range="24h" />
    );
    await user.tab();
    for (let step = 0; step < 20; step += 1) {
      await user.keyboard("{ArrowRight}");
    }
    expect(bars(container)[20]).toHaveFocus();

    const fewer = { ...data, slices: data.slices?.slice(0, 12) };
    rerender(<ThroughputBars data={fewer} range="24h" />);

    const stops = bars(container).filter(
      (bar) => bar.getAttribute("tabindex") === "0"
    );
    expect(bars(container)).toHaveLength(12);
    expect(stops).toEqual([bars(container)[11]]);
  });

  it("keeps keyboard focus when a poll moves every slice's bounds", async () => {
    installChartLayout(600);
    const user = setupUser();
    const { container, rerender } = render(
      <ThroughputBars data={data} range="all" />
    );
    await user.tab();
    await user.keyboard("{ArrowRight}{ArrowRight}{ArrowRight}");
    const focused = bars(container)[3];
    expect(focused).toHaveFocus();

    const shift = (iso: string) =>
      new Date(Date.parse(iso) + 60_000).toISOString();
    const moved = {
      ...data,
      window_start: shift(data.window_start),
      window_end: shift(data.window_end),
      slices: data.slices?.map((slice) => ({
        ...slice,
        start: shift(slice.start),
        end: shift(slice.end),
      })),
    };
    rerender(<ThroughputBars data={moved} range="all" />);

    expect(bars(container)[3]).toBe(focused);
    expect(focused).toHaveFocus();
  });

  it("a failed run spanning slices is one tab stop, where it began", () => {
    installChartLayout(600);
    const run = { attempt_id: 601, status: "failed", resolved: false } as const;
    const spanning = throughputFixture({
      runs: { 5: [run], 6: [run], 7: [run] },
    });
    const { container } = render(
      <ThroughputBars data={spanning} range="24h" />
    );
    const failed = statusLines(container).filter((line) =>
      usesToken(line, FAILED_TOKEN)
    );
    expect(failed).toHaveLength(3);
    expect(failed.map((line) => line.getAttribute("tabindex"))).toEqual([
      "0",
      "-1",
      "-1",
    ]);
  });

  it("a failure line's tooltip counts only open runs, and shows on keyboard focus", async () => {
    installChartLayout(600);
    const counted = throughputFixture({
      runs: {
        5: [
          { attempt_id: 501, status: "failed", resolved: false },
          { attempt_id: 503, status: "failed", resolved: false },
          { attempt_id: 507, status: "failed", resolved: true },
          { attempt_id: 504, status: "completed_with_errors", resolved: false },
          { attempt_id: 505, status: "completed_with_errors", resolved: false },
          { attempt_id: 506, status: "completed_with_errors", resolved: false },
          { attempt_id: 508, status: "completed_with_errors", resolved: true },
        ],
      },
    });
    const { container } = render(<ThroughputBars data={counted} range="24h" />);
    const failed = statusLines(container).find((line) =>
      usesToken(line, FAILED_TOKEN)
    );
    expect(failed).toBeDefined();

    failed!.focus();

    await waitFor(() =>
      expect(document.body.textContent).toContain("2 failures, 3 errors")
    );
  });

  it("an activity hovered outside the window fades no line and draws no guide", () => {
    installChartLayout(600);
    const { container } = render(
      <ThroughputBars
        data={throughputFixture({
          runs: {
            2: [{ attempt_id: 201, status: "in_progress", resolved: false }],
            5: [{ attempt_id: 501, status: "failed", resolved: false }],
          },
        })}
        range="24h"
        hoveredAttemptId={999}
      />
    );

    expect(statusLines(container)).toHaveLength(2);
    for (const line of statusLines(container)) {
      expect(isFaded(line, container)).toBe(false);
    }
    expect(container.querySelector('[class*="dashed"]')).toBeNull();
  });
});

describe("loading", () => {
  function respond(body: unknown): Response {
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }

  it("keeps the last bars, dimmed, while a new window loads", async () => {
    jest.spyOn(Date.prototype, "getTimezoneOffset").mockReturnValue(0);
    installChartLayout(600);
    global.fetch = jest.fn((input: RequestInfo | URL) =>
      String(input).includes("window=24h")
        ? Promise.resolve(respond(throughputFixture({ docs: { 2: 40 } })))
        : new Promise<Response>(() => {})
    ) as unknown as typeof fetch;
    const { container, rerender } = render(
      <ThroughputChart ccPairId={7} range="24h" />
    );
    await waitFor(() => expect(bars(container)).toHaveLength(FIXTURE_BINS));
    expect(isFaded(bars(container)[2]!, container)).toBe(false);

    rerender(<ThroughputChart ccPairId={7} range="7d" />);

    await waitFor(() =>
      expect(isFaded(bars(container)[2]!, container)).toBe(true)
    );
    expect(bars(container)).toHaveLength(FIXTURE_BINS);
  });

  it("does not fetch while the chart is hidden at width 0", async () => {
    installChartLayout(0);
    const fetchMock = jest.fn(async () => respond(throughputFixture()));
    global.fetch = fetchMock as unknown as typeof fetch;

    render(<ThroughputChart ccPairId={7} range="24h" />);
    // SWR fetches from its mount effect, so flushing effects is enough.
    await act(async () => {});

    expect(fetchMock).not.toHaveBeenCalled();
  });
});
