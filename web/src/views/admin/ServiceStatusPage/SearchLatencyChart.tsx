"use client";

import { useState } from "react";
import {
  ComposedChart,
  ResponsiveContainer,
  XAxis,
  YAxis,
  useXAxisScale,
  useYAxisScale,
} from "recharts";
import { cn } from "@opal/utils";
import type { SearchRatePoint, SearchSample } from "@/lib/service-status/types";
import {
  BAND_COLOR,
  BAND_OPACITY,
  MARK_COLOR,
  CHART_HEIGHT_CLASS,
  CHART_MARGIN,
  HEALTHY_COLOR,
  SAMPLE_COLOR,
  SAMPLE_MAX_OPACITY,
  SAMPLE_OPACITY,
  SLOW_COLOR,
  timeAxisProps,
} from "@/views/admin/ServiceStatusPage/chartFrame";

// Latency spans 1 ms to the 60 s client timeout, so the axis is logarithmic.
const Y_MIN_MS = 1;
// The axis reaches a step past the fastest and slowest value, so nothing sits
// on an edge.
const Y_PADDING_FACTOR = 2;
// The axis of an empty chart.
const EMPTY_DOMAIN_MS: [number, number] = [1, 1000];
const MINUTE_MS = 60_000;
const DOT_RADIUS = 1.5;
const LINE_WIDTH = 2;
// A minute with no neighbors still shows its p90, as a short dash.
const LONE_DASH_HALF_WIDTH = 4;
const MARK_RADIUS = 3;
// Space between the marked column and its card.
const CARD_OFFSET_PX = 8;

interface Dot {
  // The middle of the minute the search finished in: a minute's dots share
  // one column.
  at_ms: number;
  duration_ms: number;
}

interface Percentiles {
  minute_ms: number;
  at_ms: number;
  p10_ms: number;
  p90_ms: number;
}

const minuteMiddle = (ms: number) =>
  Math.floor(ms / MINUTE_MS) * MINUTE_MS + MINUTE_MS / 2;

/** Splits the minutes into runs of consecutive minutes that had searches. */
function runsOf(rate: SearchRatePoint[]): Percentiles[][] {
  const runs: Percentiles[][] = [];
  let run: Percentiles[] = [];
  for (const point of rate) {
    if (point.p10_ms === null || point.p90_ms === null) {
      if (run.length > 0) runs.push(run);
      run = [];
      continue;
    }
    run.push({
      minute_ms: point.minute_ms,
      at_ms: minuteMiddle(point.minute_ms),
      p10_ms: Math.max(point.p10_ms, Y_MIN_MS),
      p90_ms: Math.max(point.p90_ms, Y_MIN_MS),
    });
  }
  if (run.length > 0) runs.push(run);
  return runs;
}

interface Selection {
  minute_ms: number;
  // The column's x in the chart, where the card shows.
  x: number;
  chartWidth: number;
}

interface PlotProps {
  runs: Percentiles[][];
  slowP90Ms: number;
  dots: Dot[];
  domain: [number, number];
  selectedMinuteMs: number | null;
  onSelect: (selection: Selection | null) => void;
  describeMinute: (minuteMs: number) => string;
}

/**
 * Drawn as one layer so the order is fixed: the p10 to p90 band, the dots,
 * the p90 line, then a pointer target over each minute's column. The line is
 * green while the p90 is fast; a segment turns the slow color only when both
 * of its minutes are above slowP90Ms.
 */
function Plot({
  runs,
  slowP90Ms,
  dots,
  domain,
  selectedMinuteMs,
  onSelect,
  describeMinute,
}: PlotProps) {
  const xScale = useXAxisScale();
  const yScale = useYAxisScale();
  if (!xScale || !yScale) return null;
  const x = (atMs: number) => xScale(atMs) ?? 0;
  const y = (ms: number) => yScale(ms) ?? 0;
  const color = (ms: number) => (ms > slowP90Ms ? SLOW_COLOR : HEALTHY_COLOR);
  const columnWidth = Math.abs(x(MINUTE_MS) - x(0));
  const plotTop = y(domain[1]);
  const plotBottom = y(domain[0]);
  const selected = runs
    .flat()
    .find((point) => point.minute_ms === selectedMinuteMs);
  const select = (point: Percentiles, target: SVGRectElement) => {
    const svg = target.ownerSVGElement;
    if (!svg) return;
    onSelect({
      minute_ms: point.minute_ms,
      x: x(point.at_ms),
      chartWidth: svg.getBoundingClientRect().width,
    });
  };

  return (
    <g>
      {runs.map((run) => {
        const top = run.map((point) => `${x(point.at_ms)},${y(point.p90_ms)}`);
        const bottom = [...run]
          .reverse()
          .map((point) => `${x(point.at_ms)},${y(point.p10_ms)}`);
        return (
          <polygon
            key={run[0]!.at_ms}
            points={[...top, ...bottom].join(" ")}
            fill={BAND_COLOR}
            fillOpacity={BAND_OPACITY}
          />
        );
      })}
      <g opacity={SAMPLE_MAX_OPACITY}>
        {dots.map((dot, index) => (
          <circle
            key={index}
            cx={x(dot.at_ms)}
            cy={y(dot.duration_ms)}
            r={DOT_RADIUS}
            fill={SAMPLE_COLOR}
            fillOpacity={SAMPLE_OPACITY}
          />
        ))}
      </g>
      <g strokeWidth={LINE_WIDTH} strokeLinecap="round">
        {runs.flatMap((run) => {
          const first = run[0]!;
          if (run.length === 1) {
            return [
              <line
                key={first.at_ms}
                x1={x(first.at_ms) - LONE_DASH_HALF_WIDTH}
                x2={x(first.at_ms) + LONE_DASH_HALF_WIDTH}
                y1={y(first.p90_ms)}
                y2={y(first.p90_ms)}
                stroke={color(first.p90_ms)}
              />,
            ];
          }
          return run.slice(1).map((point, index) => {
            const previous = run[index]!;
            return (
              <line
                key={point.at_ms}
                x1={x(previous.at_ms)}
                x2={x(point.at_ms)}
                y1={y(previous.p90_ms)}
                y2={y(point.p90_ms)}
                // A rise or drop across the threshold stays green.
                stroke={color(Math.min(previous.p90_ms, point.p90_ms))}
              />
            );
          });
        })}
      </g>
      {selected && (
        <g>
          <line
            x1={x(selected.at_ms)}
            x2={x(selected.at_ms)}
            y1={plotTop}
            y2={plotBottom}
            stroke={MARK_COLOR}
          />
          <circle
            cx={x(selected.at_ms)}
            cy={y(selected.p90_ms)}
            r={MARK_RADIUS}
            fill={color(selected.p90_ms)}
          />
          <circle
            cx={x(selected.at_ms)}
            cy={y(selected.p10_ms)}
            r={MARK_RADIUS}
            fill={MARK_COLOR}
          />
        </g>
      )}
      {runs.flat().map((point) => (
        <rect
          key={point.minute_ms}
          x={x(point.at_ms) - columnWidth / 2}
          y={plotTop}
          width={columnWidth}
          height={plotBottom - plotTop}
          fill="transparent"
          role="button"
          tabIndex={0}
          aria-label={describeMinute(point.minute_ms)}
          onMouseEnter={(event) => select(point, event.currentTarget)}
          onFocus={(event) => select(point, event.currentTarget)}
          // A tap on a touch screen has no hover.
          onClick={(event) => select(point, event.currentTarget)}
          onMouseLeave={() => onSelect(null)}
          onBlur={() => onSelect(null)}
        />
      ))}
    </g>
  );
}

interface SearchLatencyChartProps {
  rate: SearchRatePoint[];
  // A p90 above this draws the line in the slow color.
  slowP90Ms: number;
  samples: SearchSample[];
  startMs: number;
  endMs: number;
  formatTime: (ms: number) => string;
  // The card for a marked minute: its p90 and p10.
  renderMinute: (minuteMs: number) => React.ReactNode;
  // The same for a screen reader, as each minute's label.
  describeMinute: (minuteMs: number) => string;
}

/**
 * One dot per successful search, in the column of the minute it finished in,
 * over each minute's p10 to p90 band, with the p90 line on top. Hovering,
 * focusing or tapping a minute marks its p90 and p10 and shows a card with
 * both; it closes when the pointer or focus leaves. Failed searches have no
 * useful duration; the Search Load chart shows them.
 */
export default function SearchLatencyChart({
  rate,
  slowP90Ms,
  samples,
  startMs,
  endMs,
  formatTime,
  renderMinute,
  describeMinute,
}: SearchLatencyChartProps) {
  const [selection, setSelection] = useState<Selection | null>(null);
  const dots: Dot[] = samples
    .filter((sample) => sample.result === "ok")
    .map((sample) => ({
      at_ms: minuteMiddle(sample.at_ms),
      duration_ms: Math.max(sample.client_ms, Y_MIN_MS),
    }));
  const runs = runsOf(rate);
  const values = [
    ...dots.map((dot) => dot.duration_ms),
    ...runs.flat().flatMap((point) => [point.p10_ms, point.p90_ms]),
  ];
  const domain: [number, number] =
    values.length === 0
      ? EMPTY_DOMAIN_MS
      : [
          Math.max(Y_MIN_MS, Math.min(...values) / Y_PADDING_FACTOR),
          Math.max(...values) * Y_PADDING_FACTOR,
        ];
  // Recharts builds an axis scale only from chart data, so the two corners of
  // the plot carry the axes, with or without searches.
  const axisData = [
    { at_ms: startMs, ms: domain[0] },
    { at_ms: endMs, ms: domain[1] },
  ];

  return (
    // dir="ltr": time runs left to right in every locale.
    <div
      dir="ltr"
      className={cn(CHART_HEIGHT_CLASS, "relative w-full font-secondary-mono")}
    >
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={axisData} margin={CHART_MARGIN}>
          <XAxis {...timeAxisProps(startMs, endMs, formatTime)} />
          <YAxis hide dataKey="ms" type="number" scale="log" domain={domain} />
          <Plot
            runs={runs}
            slowP90Ms={slowP90Ms}
            dots={dots}
            domain={domain}
            selectedMinuteMs={selection?.minute_ms ?? null}
            onSelect={setSelection}
            describeMinute={describeMinute}
          />
        </ComposedChart>
      </ResponsiveContainer>
      {selection && (
        // On the side with more room, so it does not cover the column.
        <div
          className="pointer-events-none absolute top-0 z-10"
          style={
            selection.x < selection.chartWidth / 2
              ? { left: selection.x + CARD_OFFSET_PX }
              : { right: selection.chartWidth - selection.x + CARD_OFFSET_PX }
          }
        >
          {renderMinute(selection.minute_ms)}
        </div>
      )}
    </div>
  );
}
