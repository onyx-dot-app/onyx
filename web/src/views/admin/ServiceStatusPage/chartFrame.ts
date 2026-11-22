/**
 * What both search charts share: height, margins and the time axis.
 */

export const CHART_HEIGHT_CLASS = "h-[96px]";

// The charts have no y-axis. The side margins keep the start and end time
// labels inside the chart; the top margin keeps the highest marks whole.
export const CHART_MARGIN = {
  top: 10,
  right: 20,
  left: 20,
  bottom: 0,
} as const;

// Resolved through var() so the charts follow the active theme.
export const AXIS_TEXT_COLOR = "var(--text-03)";
export const GRID_COLOR = "var(--border-01)";

export const AXIS_TICK = { fill: AXIS_TEXT_COLOR, fontSize: 11 } as const;

// Series colors.
export const SEARCH_COLOR = "var(--theme-green-05)";
export const FAILED_COLOR = "var(--status-error-05)";
// Search Latency: grey dots, one per search, over a light p10 to p90 band.
// The p90 line is green while fast and amber while slow.
export const SAMPLE_COLOR = "var(--text-05)";
// Each dot has SAMPLE_OPACITY inside a group at SAMPLE_MAX_OPACITY, so a single
// dot shows at 5% and dots that overlap read darker, up to 50%.
export const SAMPLE_OPACITY = 0.1;
export const SAMPLE_MAX_OPACITY = 0.5;
export const BAND_COLOR = "var(--text-05)";
export const BAND_OPACITY = 0.05;
export const HEALTHY_COLOR = "var(--theme-green-05)";
export const SLOW_COLOR = "var(--theme-amber-04)";
// The marks of the minute under the pointer.
export const MARK_COLOR = "var(--text-03)";

/**
 * The time axis: the window ends with the current minute, labeled only at its
 * start and end.
 */
export function timeAxisProps(
  startMs: number,
  endMs: number,
  formatTime: (ms: number) => string
) {
  return {
    type: "number" as const,
    dataKey: "at_ms",
    domain: [startMs, endMs],
    ticks: [startMs, endMs],
    tickFormatter: formatTime,
    tick: AXIS_TICK,
    tickLine: false,
    axisLine: { stroke: GRID_COLOR },
    tickMargin: 6,
    interval: 0 as const,
  };
}
