"use client";

import { useState } from "react";
import useSWR from "swr";
import { useFormatter, useTranslations } from "next-intl";
import {
  Bar,
  BarChart,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
} from "recharts";
import {
  Card,
  Dropdown,
  FilterButton,
  MessageCard,
  OpenButton,
  Text,
} from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgClock } from "@opal/icons";
import { LineLoader } from "@opal/loaders";
import { cn } from "@opal/utils";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  CCPairThroughputResponse,
  CCPairThroughputWindow,
} from "@/lib/connectors/types";
import type { ValidStatuses } from "@/lib/types";

export const THROUGHPUT_POLL_MS = 30_000;
const BARS_HEIGHT = 48;
const AXIS_HEIGHT = 16;
const DAY_MINUTES = 1440;
const HOUR_MINUTES = 60;

// Labels sit on local times divisible by this. At a day they fall on midnight and show the date.
const TICK_MINUTES = {
  "1h": 10,
  "12h": 2 * HOUR_MINUTES,
  "24h": 4 * HOUR_MINUTES,
  "7d": DAY_MINUTES,
} satisfies Record<CCPairThroughputWindow, number>;

// A zoomed span labels the coarsest of these that still fits this many labels.
const SPAN_TICK_MINUTES = [
  1,
  5,
  10,
  30,
  HOUR_MINUTES,
  2 * HOUR_MINUTES,
  4 * HOUR_MINUTES,
  DAY_MINUTES,
];
const SPAN_TICKS_WANTED = 3;

/** Tick spacing for a zoomed span, so a span of any length keeps a few labels. */
function spanTickMinutes(spanMs: number): number {
  const spanMinutes = spanMs / 60_000;
  const fitting = SPAN_TICK_MINUTES.filter(
    (minutes) => spanMinutes / minutes >= SPAN_TICKS_WANTED
  );
  return fitting[fitting.length - 1] ?? 1;
}

/** A window a picker offers. */
export type PickerWindow = CCPairThroughputWindow;

// The pair chart has no 1h window: one hour of a pair is too few runs to read.
export const PAIR_WINDOWS: readonly PickerWindow[] = ["12h", "24h", "7d"];

/** Each window's label under `admin.connector.runs.window`. */
export const WINDOW_LABEL_KEYS = {
  "1h": "h1",
  "12h": "h12",
  "24h": "h24",
  "7d": "d7",
} as const satisfies Record<PickerWindow, string>;

function windowLabelKey(window: PickerWindow) {
  return WINDOW_LABEL_KEYS[window];
}

const WINDOW_HOURS = {
  "1h": 1,
  "12h": 12,
  "24h": 24,
  "7d": 24 * 7,
} satisfies Record<PickerWindow, number>;

export interface PickedWindow {
  window: PickerWindow;
}

export function pickWindow(window: PickerWindow): PickedWindow {
  return { window };
}

/**
 * The start of a window that ends now, to the minute, so the run list keeps
 * pace with the chart (whose window the backend moves on every poll) while
 * its cache key changes only once a minute.
 */
export function windowStart(hours: number): string {
  const minute = Math.floor(Date.now() / 60_000) * 60_000;
  return new Date(minute - hours * 3_600_000).toISOString();
}

export function pickedWindowStart({ window }: PickedWindow): string {
  return windowStart(WINDOW_HOURS[window]);
}

/** A chart slice or dragged span, as ISO times, that zooms the chart and narrows its run lists. `until` is exclusive. */
export interface SliceRange {
  since: string;
  until: string;
}

/** The narrower of a window start and a slice, so a slice never reaches past the window it sits in. */
export function rangeWithin(
  since: string | null,
  range: SliceRange | null
): { since: string | null; until: string | null } {
  if (range === null) return { since, until: null };
  return {
    since:
      since !== null && Date.parse(since) > Date.parse(range.since)
        ? since
        : range.since,
    until: range.until,
  };
}

const SLICE_TIME_FORMAT = {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
} as const;

// The status strip draws this many hairline ticks under each bar, so a run reads as
// thin ticks with gaps between them rather than a solid block.
const STRIP_TICKS_PER_SLICE = 2;

// The status strip's tick color for a span a run of that status covered.
const RUN_CELL_CLASS: Record<ValidStatuses, string> = {
  success: "bg-action-selection-02",
  in_progress: "bg-theme-blue-05",
  not_started: "bg-theme-blue-05",
  completed_with_errors: "bg-status-warning-05",
  failed: "bg-status-error-05",
  invalid: "bg-status-error-05",
  canceled: "bg-background-neutral-03",
  interrupted: "bg-background-neutral-03",
};

interface Slice {
  /** The slice's middle, where its bar sits. */
  at: number;
  docs: number;
}

/** The local times inside the window that are a whole multiple of `minutes` past local midnight. */
function axisTicks(start: number, end: number, minutes: number): number[] {
  // Ticks within an hour step by their own spacing, longer ones hour by hour so a day's ticks still land on midnight across a clock change.
  const step = Math.min(minutes, HOUR_MINUTES);
  const tick = new Date(start);
  tick.setSeconds(0, 0);
  tick.setMinutes(tick.getMinutes() - (tick.getMinutes() % step));
  const ticks: number[] = [];
  for (; tick.getTime() <= end; tick.setMinutes(tick.getMinutes() + step)) {
    const sinceMidnight = tick.getHours() * HOUR_MINUTES + tick.getMinutes();
    if (tick.getTime() >= start && sinceMidnight % minutes === 0) {
      ticks.push(tick.getTime());
    }
  }
  return ticks;
}

/** Unlabeled ticks at a third of the label spacing, inside the window. */
function minorTicks(
  labels: number[],
  start: number,
  end: number,
  minutes: number
): number[] {
  const third = (minutes * 60_000) / 3;
  const ticks = new Set<number>();
  for (const label of labels) {
    for (const offset of [-2, -1, 1, 2]) {
      const tick = label + offset * third;
      if (tick >= start && tick <= end) ticks.add(tick);
    }
  }
  return Array.from(ticks);
}

interface Run {
  start: number;
  end: number;
  status: ValidStatuses;
}

// A slice several runs covered shows the one that needs attention most.
const STATUS_SEVERITY: Record<ValidStatuses, number> = {
  failed: 5,
  invalid: 5,
  completed_with_errors: 4,
  in_progress: 3,
  not_started: 3,
  success: 2,
  canceled: 1,
  interrupted: 1,
};

/** The status of the run that covered the span, the most severe when several did. */
function sliceStatus(
  runs: Run[],
  sliceStart: number,
  sliceEnd: number
): ValidStatuses | null {
  let shown: Run | null = null;
  for (const run of runs) {
    // An instant run (one that failed at once) covers the slice it began in.
    if (
      run.start >= sliceEnd ||
      Math.max(run.end, run.start + 1) <= sliceStart
    ) {
      continue;
    }
    if (
      shown === null ||
      STATUS_SEVERITY[run.status] > STATUS_SEVERITY[shown.status]
    ) {
      shown = run;
    }
  }
  return shown?.status ?? null;
}

export interface ThroughputWindowPickerProps<W extends PickerWindow> {
  windows: readonly W[];
  value: W;
  onChange: (window: W) => void;
  /** A span picked on the chart. The picker shows it in place of the window, with an X that calls `onClearSelection`. */
  selection?: SliceRange | null;
  onClearSelection?: () => void;
}

/** Picks how far back a throughput chart, and any list that shares it, reaches, and shows the span picked inside it. */
export function ThroughputWindowPicker<W extends PickerWindow>({
  windows,
  value,
  onChange,
  selection = null,
  onClearSelection,
}: ThroughputWindowPickerProps<W>) {
  const t = useTranslations("admin.connector.statusCard.throughput");
  const tWindow = useTranslations("admin.connector.runs.window");
  const format = useFormatter();
  return (
    <Dropdown>
      <Dropdown.Trigger asChild>
        {selection === null || onClearSelection === undefined ? (
          <OpenButton icon={SvgClock} state="empty">
            {tWindow(windowLabelKey(value))}
          </OpenButton>
        ) : (
          // The span takes the picker's place, so the row keeps its shape. Its X returns to the window.
          <FilterButton
            icon={SvgClock}
            active
            tooltip={t("rangeFilter")}
            onClear={onClearSelection}
          >
            {format.dateTimeRange(
              new Date(selection.since),
              new Date(selection.until),
              SLICE_TIME_FORMAT
            )}
          </FilterButton>
        )}
      </Dropdown.Trigger>
      <Dropdown.Data
        label={tWindow("label")}
        value={value}
        onSelect={(option) => {
          const picked = windows.find((window) => window === option.value);
          if (picked !== undefined) onChange(picked);
        }}
        items={windows.map((window) => ({
          kind: "option" as const,
          value: window,
          title: tWindow(windowLabelKey(window)),
        }))}
      />
    </Dropdown>
  );
}

interface SliceTooltipProps {
  active?: boolean;
  payload?: { payload: Slice }[];
  sliceMs: number;
}
function SliceTooltip({ active, payload, sliceMs }: SliceTooltipProps) {
  const t = useTranslations("admin.connector.statusCard.throughput");
  const format = useFormatter();
  const slice = payload?.[0]?.payload;
  if (!active || slice === undefined) return null;
  const from = new Date(slice.at - sliceMs / 2);
  const to = new Date(slice.at + sliceMs / 2);
  return (
    <Card border="solid" rounding={2} padding={1}>
      <Text font="secondary-action" color="text-04">
        {t("tooltip", { count: slice.docs })}
      </Text>
      <Text font="secondary-body" color="text-03">
        {format.dateTimeRange(from, to, SLICE_TIME_FORMAT)}
      </Text>
    </Card>
  );
}

/** A drag across the bars, as the indices of the first and the latest slice under the pointer. */
interface Drag {
  from: number;
  to: number;
}

export interface ThroughputBarsProps {
  data: CCPairThroughputResponse;
  range: CCPairThroughputWindow;
  /** The bars' height in pixels, above the axis. */
  height?: number;
  /** Zooms the chart to this span of its window. */
  selection?: SliceRange | null;
  /** Lets a click pick one slice and a drag pick a span. */
  onRangeSelect?: (range: SliceRange) => void;
}

/** Documents indexed in each slice of a window, over a strip that colors each slice by the run that covered it. */
export function ThroughputBars({
  data,
  range,
  height = BARS_HEIGHT,
  selection = null,
  onRangeSelect,
}: ThroughputBarsProps) {
  const t = useTranslations("admin.connector.statusCard.throughput");
  const format = useFormatter();
  const [drag, setDrag] = useState<Drag | null>(null);
  const dataStart = Date.parse(data.window_start);
  const dataEnd = Date.parse(data.window_end);
  const sliceMs = (dataEnd - dataStart) / data.docs_indexed.length;
  const tickMs = sliceMs / STRIP_TICKS_PER_SLICE;
  // A selection shows only the slices that overlap it, so the bars widen to fill the span and a
  // slice that drifts half out as the window rolls keeps its bar, clipped at the axis, until it leaves.
  const start = selection === null ? dataStart : Date.parse(selection.since);
  const end = selection === null ? dataEnd : Date.parse(selection.until);
  const slices: Slice[] = data.docs_indexed
    .map((docs, index) => ({
      at: dataStart + sliceMs * (index + 0.5),
      docs,
    }))
    .filter(
      (slice) => slice.at + sliceMs / 2 > start && slice.at - sliceMs / 2 < end
    );
  const tickMinutes =
    selection === null ? TICK_MINUTES[range] : spanTickMinutes(end - start);
  const labelTicks = axisTicks(start, end, tickMinutes);
  const labelSet = new Set(labelTicks);
  const ticks = [
    ...labelTicks,
    ...minorTicks(labelTicks, start, end, tickMinutes),
  ].sort((a, b) => a - b);
  // A run still going covers up to the window's end.
  const runs: Run[] = data.runs.map((run) => ({
    start: Date.parse(run.started),
    end: run.ended === null ? dataEnd : Date.parse(run.ended),
    status: run.status,
  }));

  function sliceIndex(activeTooltipIndex: number | string | null | undefined) {
    return activeTooltipIndex == null ? null : Number(activeTooltipIndex);
  }
  // The dragged span widened to its slices' edges, or null before a drag or once it left the bars.
  const first =
    drag === null ? undefined : slices[Math.min(drag.from, drag.to)];
  const last = drag === null ? undefined : slices[Math.max(drag.from, drag.to)];
  const dragBounds =
    first === undefined || last === undefined
      ? null
      : { from: first.at - sliceMs / 2, to: last.at + sliceMs / 2 };
  // The drag ends on the pointer's release or when it leaves the chart, and its span is what it covered.
  function endDrag() {
    setDrag(null);
    if (onRangeSelect === undefined || dragBounds === null) return;
    onRangeSelect({
      since: new Date(dragBounds.from).toISOString(),
      until: new Date(dragBounds.to).toISOString(),
    });
  }

  return (
    // The SVG never flips for right-to-left text, so the strip must not either.
    <Section alignItems="stretch" gap={0.5} height="fit" dir="ltr">
      {/* raw-ok: the chart is an SVG image, Section has no img role */}
      <div
        role="img"
        aria-label={t("ariaLabel")}
        // Recharts focuses its surface on click; only keyboard focus gets a ring.
        className="w-full select-none [&_:focus:not(:focus-visible)]:outline-none"
      >
        <ResponsiveContainer width="100%" height={height + AXIS_HEIGHT}>
          <BarChart
            data={slices}
            margin={{ top: 0, right: 0, bottom: 0, left: 0 }}
            barCategoryGap={1.5}
            // The whole column takes the pointer, so a slice with no documents but a failed run can be picked too.
            onMouseDown={
              onRangeSelect === undefined
                ? undefined
                : ({ activeTooltipIndex }) => {
                    const index = sliceIndex(activeTooltipIndex);
                    if (index !== null) setDrag({ from: index, to: index });
                  }
            }
            onMouseMove={
              drag === null
                ? undefined
                : ({ activeTooltipIndex }) => {
                    const index = sliceIndex(activeTooltipIndex);
                    if (index !== null && index !== drag.to) {
                      setDrag({ from: drag.from, to: index });
                    }
                  }
            }
            onMouseUp={drag === null ? undefined : endDrag}
            onMouseLeave={drag === null ? undefined : endDrag}
            style={
              onRangeSelect === undefined ? undefined : { cursor: "pointer" }
            }
          >
            <XAxis
              dataKey="at"
              type="number"
              scale="time"
              domain={[start, end]}
              allowDataOverflow
              ticks={ticks}
              tickFormatter={(value: number) =>
                !labelSet.has(value)
                  ? ""
                  : tickMinutes >= DAY_MINUTES
                    ? format.dateTime(new Date(value), {
                        month: "short",
                        day: "numeric",
                      })
                    : format.dateTime(new Date(value), {
                        hour: "2-digit",
                        minute: "2-digit",
                        hourCycle: "h23",
                      })
              }
              tick={{
                fontSize: 10,
                fontFamily: "var(--font-dm-mono)",
                fill: "var(--text-03)",
              }}
              axisLine={{ stroke: "var(--border-01)" }}
              tickLine={{ stroke: "var(--border-01)" }}
              tickSize={2}
              height={AXIS_HEIGHT}
            />
            <Tooltip
              cursor={{ fill: "var(--background-tint-02)" }}
              content={<SliceTooltip sliceMs={sliceMs} />}
              isAnimationActive={false}
            />
            {dragBounds !== null && (
              <ReferenceArea
                x1={dragBounds.from}
                x2={dragBounds.to}
                fill="var(--action-selection-01)"
                fillOpacity={1}
                stroke="var(--action-selection-02)"
              />
            )}
            <Bar
              dataKey="docs"
              fill="var(--theme-blue-05)"
              radius={[1, 1, 0, 0]}
              isAnimationActive={false}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
      {/* raw-ok: a 10px strip of over a hundred 1px hairlines, below Section's smallest height and gap steps */}
      <div className="flex h-2.5 w-full" aria-hidden>
        {Array.from(
          { length: Math.round((end - start) / tickMs) },
          (_, index) => {
            const tickStart = start + index * tickMs;
            const status = sliceStatus(runs, tickStart, tickStart + tickMs);
            return (
              // raw-ok: one slot per hairline, centered so the gaps hold at any width
              <div key={tickStart} className="flex flex-1 justify-center">
                {status !== null && (
                  <div
                    className={cn(
                      "h-full w-px rounded-full",
                      RUN_CELL_CLASS[status]
                    )}
                  />
                )}
              </div>
            );
          }
        )}
      </div>
    </Section>
  );
}

export interface ThroughputChartProps {
  ccPairId: number;
  range: CCPairThroughputWindow;
  selection?: SliceRange | null;
  onRangeSelect?: (range: SliceRange) => void;
}

/** One pair's throughput over the window, polled. */
export default function ThroughputChart({
  ccPairId,
  range,
  selection = null,
  onRangeSelect,
}: ThroughputChartProps) {
  const t = useTranslations("admin.connector.statusCard.throughput");
  const { data, error } = useSWR<CCPairThroughputResponse>(
    SWR_KEYS.ccPairThroughput(ccPairId, range),
    errorHandlingFetcher,
    { refreshInterval: THROUGHPUT_POLL_MS, keepPreviousData: true }
  );
  if (error !== undefined) {
    return <MessageCard variant="error" title={t("loadError")} />;
  }
  if (data === undefined) return <LineLoader lines={3} />;
  return (
    <ThroughputBars
      data={data}
      range={range}
      selection={selection}
      onRangeSelect={onRangeSelect}
    />
  );
}
