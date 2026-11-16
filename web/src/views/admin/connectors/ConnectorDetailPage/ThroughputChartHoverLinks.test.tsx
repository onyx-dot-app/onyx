/** The chart's links to the activity panel: a failure line click focuses its run, a hovered activity keeps its line and draws a dashed guide, and a hovered line reports the runs that started in its slice. */
import { render, setupUser } from "@tests/setup/test-utils";
import { ThroughputBars } from "@/views/admin/connectors/ConnectorDetailPage/ThroughputChart";
import {
  installChartLayout,
  isFaded,
  resetChartLayout,
  throughputFixture,
  usesToken,
} from "@tests/setup/throughputChartTestUtils";

beforeEach(() => installChartLayout(600));
afterEach(() => resetChartLayout());

const RUNNING_TOKEN = "chart-sequential-mass-02-blue";
const FAILED_TOKEN = "chart-diverging-neg-10-red";
const RESOLVED_TOKEN = "chart-diverging-neg-02-red";

// Run 201 started in slice 2 and is still running through slice 4.
const data = throughputFixture({
  docs: { 2: 40, 3: 40, 4: 40, 5: 12 },
  runs: {
    2: [{ attempt_id: 201, status: "in_progress", resolved: false }],
    3: [{ attempt_id: 201, status: "in_progress", resolved: false }],
    4: [{ attempt_id: 201, status: "in_progress", resolved: false }],
    5: [
      { attempt_id: 501, status: "failed", resolved: false },
      { attempt_id: 502, status: "failed", resolved: true },
    ],
  },
});

function statusLines(container: HTMLElement): HTMLElement[] {
  return Array.from(
    container.querySelectorAll<HTMLElement>('[data-testid="chart-status-line"]')
  );
}

function lineWith(container: HTMLElement, token: string, nth = 0): HTMLElement {
  const line = statusLines(container).filter((candidate) =>
    usesToken(candidate, token)
  )[nth];
  if (line === undefined) throw new Error(`no ${token} line #${nth}`);
  return line;
}

function dashedGuide(container: HTMLElement): Element | null {
  return container.querySelector(
    '[stroke-dasharray]:not([stroke-dasharray="none"]):not([stroke-dasharray="0"]), [class*="dashed"], [style*="dashed"]'
  );
}

describe("AC-4: failure line focuses its activity", () => {
  it("AC-4: a click on a failure line focuses that run", async () => {
    const onFocusAttempt = jest.fn();
    const user = setupUser();
    const { container } = render(
      <ThroughputBars data={data} range="24h" onFocusAttempt={onFocusAttempt} />
    );

    const failed = lineWith(container, FAILED_TOKEN);
    expect(failed).toHaveAttribute("role", "button");
    await user.click(failed);

    expect(onFocusAttempt).toHaveBeenCalledWith(501);
  });
});

describe("AC-6: hover links", () => {
  it("AC-6: no activity hovered: no line fades and no guide draws", () => {
    const { container } = render(
      <ThroughputBars data={data} range="24h" hoveredAttemptId={null} />
    );

    expect(statusLines(container).length).toBeGreaterThan(0);
    for (const line of statusLines(container)) {
      expect(isFaded(line, container)).toBe(false);
    }
    expect(dashedGuide(container)).toBeNull();
  });

  it("AC-6: a hovered activity keeps its line, fades the others and draws a dashed guide", () => {
    const { container, rerender } = render(
      <ThroughputBars data={data} range="24h" hoveredAttemptId={null} />
    );

    rerender(<ThroughputBars data={data} range="24h" hoveredAttemptId={501} />);

    expect(isFaded(lineWith(container, FAILED_TOKEN), container)).toBe(false);
    expect(isFaded(lineWith(container, RESOLVED_TOKEN), container)).toBe(true);
    expect(isFaded(lineWith(container, RUNNING_TOKEN), container)).toBe(true);
    expect(dashedGuide(container)).not.toBeNull();
  });

  it("AC-6: hovering a status line reports the runs of that kind that started in its slice, and leaving it clears them", async () => {
    const onHoverLine = jest.fn();
    const user = setupUser();
    const { container } = render(
      <ThroughputBars data={data} range="24h" onHoverLine={onHoverLine} />
    );

    await user.hover(lineWith(container, FAILED_TOKEN));
    expect(onHoverLine).toHaveBeenLastCalledWith(
      expect.objectContaining({ attemptIds: [501] })
    );

    await user.hover(lineWith(container, RESOLVED_TOKEN));
    expect(onHoverLine).toHaveBeenLastCalledWith(
      expect.objectContaining({ attemptIds: [502] })
    );

    await user.hover(lineWith(container, RUNNING_TOKEN, 0));
    expect(onHoverLine).toHaveBeenLastCalledWith(
      expect.objectContaining({ attemptIds: [201] })
    );

    // Slice 3 holds run 201, which started in slice 2.
    await user.hover(lineWith(container, RUNNING_TOKEN, 1));
    const later = onHoverLine.mock.calls.at(-1)?.[0];
    expect(later === null || !later.attemptIds.includes(201)).toBe(true);

    await user.hover(lineWith(container, FAILED_TOKEN));
    await user.unhover(lineWith(container, FAILED_TOKEN));
    const bar = container.querySelector('[data-testid="chart-bar"]');
    expect(bar).not.toBeNull();
    await user.hover(bar!);
    expect(onHoverLine).toHaveBeenLastCalledWith(null);
  });
});
