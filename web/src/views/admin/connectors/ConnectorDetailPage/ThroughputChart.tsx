"use client";

import useSWR from "swr";
import { useFormatter, useTranslations } from "next-intl";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis } from "recharts";
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

/** A window a picker offers: a chart window, or all time where a list shares the picker. */
export type PickerWindow = CCPairThroughputWindow | "all";

/** Each window's label under `admin.connector.runs.window`. */
export const WINDOW_LABEL_KEYS = {
  "1h": "h1",
  "12h": "h12",
  "24h": "h24",
  "7d": "d7",
  all: "all",
} as const satisfies Record<PickerWindow, string>;

const WINDOW_HOURS = {
  "1h": 1,
  "12h": 12,
  "24h": 24,
  "7d": 24 * 7,
  all: null,
} satisfies Record<PickerWindow, number | null>;

function windowLabelKey(window: PickerWindow) {
  return WINDOW_LABEL_KEYS[window];
}

export interface PickedWindow {
  window: PickerWindow;
  /** The window's start, fixed when it is picked so polling keeps one cache key. `null` is all time. */
  since: string | null;
}

export function pickWindow(window: PickerWindow): PickedWindow {
  const hours = WINDOW_HOURS[window];
  return {
    window,
    since:
      hours === null
        ? null
        : new Date(Date.now() - hours * 3_600_000).toISOString(),
  };
}

/** A chart slice picked to narrow a run list, as ISO times. `until` is exclusive. */
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

export interface SliceRangeFilterProps {
  range: SliceRange;
  onClear: () => void;
}

/** The picked slice's time span as an active filter, cleared by its X. */
export function SliceRangeFilter({ range, onClear }: SliceRangeFilterProps) {
  const t = useTranslations("admin.connector.statusCard.throughput");
  const format = useFormatter();
  return (
    <FilterButton
      icon={SvgClock}
      active
      tooltip={t("rangeFilter")}
      onClear={onClear}
    >
      {format.dateTimeRange(
        new Date(range.since),
        new Date(range.until),
        SLICE_TIME_FORMAT
      )}
    </FilterButton>
  );
}

// The status strip's cell color for a slice a run of that status covered.
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

/** The status of the run that covered the slice, the most severe when several did. */
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
}

/** Picks how far back a throughput chart, and any list that shares it, reaches. */
export function ThroughputWindowPicker<W extends PickerWindow>({
  windows,
  value,
  onChange,
}: ThroughputWindowPickerProps<W>) {
  const tWindow = useTranslations("admin.connector.runs.window");
  return (
    <Dropdown>
      <Dropdown.Trigger asChild>
        <OpenButton icon={SvgClock} state="empty">
          {tWindow(windowLabelKey(value))}
        </OpenButton>
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

export interface ThroughputBarsProps {
  data: CCPairThroughputResponse;
  range: CCPairThroughputWindow;
  /** The bars' height in pixels, above the axis. */
  height?: number;
  /** Makes each slice clickable, with its start and end. */
  onSliceClick?: (start: Date, end: Date) => void;
}

/** Documents indexed in each slice of a window, over a strip that colors each slice by the run that covered it. */
export function ThroughputBars({
  data,
  range,
  height = BARS_HEIGHT,
  onSliceClick,
}: ThroughputBarsProps) {
  const t = useTranslations("admin.connector.statusCard.throughput");
  const format = useFormatter();
  const start = Date.parse(data.window_start);
  const end = Date.parse(data.window_end);
  const sliceMs = (end - start) / data.docs_indexed.length;
  const slices: Slice[] = data.docs_indexed.map((docs, index) => ({
    at: start + sliceMs * (index + 0.5),
    docs,
  }));
  const tickMinutes = TICK_MINUTES[range];
  const ticks = axisTicks(start, end, tickMinutes);
  // A run still going covers up to the window's end.
  const runs: Run[] = data.runs.map((run) => ({
    start: Date.parse(run.started),
    end: run.ended === null ? end : Date.parse(run.ended),
    status: run.status,
  }));

  return (
    // The SVG never flips for right-to-left text, so the strip must not either.
    <Section alignItems="stretch" gap={0.5} height="fit" dir="ltr">
      {/* raw-ok: the chart is an SVG image, Section has no img role */}
      <div role="img" aria-label={t("ariaLabel")} className="w-full">
        <ResponsiveContainer width="100%" height={height + AXIS_HEIGHT}>
          <BarChart
            data={slices}
            margin={{ top: 0, right: 0, bottom: 0, left: 0 }}
            barCategoryGap={1.5}
            // The whole column takes the click, so a slice with no documents but a failed run can be picked too.
            onClick={
              onSliceClick === undefined
                ? undefined
                : ({ activeTooltipIndex }) => {
                    const slice = slices[Number(activeTooltipIndex)];
                    if (activeTooltipIndex == null || slice === undefined) {
                      return;
                    }
                    onSliceClick(
                      new Date(slice.at - sliceMs / 2),
                      new Date(slice.at + sliceMs / 2)
                    );
                  }
            }
            style={
              onSliceClick === undefined ? undefined : { cursor: "pointer" }
            }
          >
            <XAxis
              dataKey="at"
              type="number"
              scale="time"
              domain={[start, end]}
              ticks={ticks}
              tickFormatter={(value: number) =>
                tickMinutes >= DAY_MINUTES
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
            />
            <Bar
              dataKey="docs"
              fill="var(--theme-blue-05)"
              radius={[1, 1, 0, 0]}
              isAnimationActive={false}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
      {/* raw-ok: the cells need a 1.5px gap, below Section's smallest spacing step */}
      <div className="flex h-2.5 w-full gap-[1.5px] px-[0.75px]" aria-hidden>
        {slices.map((slice) => {
          const status = sliceStatus(
            runs,
            slice.at - sliceMs / 2,
            slice.at + sliceMs / 2
          );
          return (
            <div
              key={slice.at}
              className={cn(
                "h-full min-w-px flex-1 rounded-[2px]",
                status === null ? undefined : RUN_CELL_CLASS[status]
              )}
            />
          );
        })}
      </div>
    </Section>
  );
}

export interface ThroughputChartProps {
  ccPairId: number;
  range: CCPairThroughputWindow;
  onSliceClick?: (start: Date, end: Date) => void;
}

/** One pair's throughput over the window, polled. */
export default function ThroughputChart({
  ccPairId,
  range,
  onSliceClick,
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
    <ThroughputBars data={data} range={range} onSliceClick={onSliceClick} />
  );
}
