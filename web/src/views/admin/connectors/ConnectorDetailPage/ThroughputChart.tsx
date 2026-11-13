"use client";

import {
  Fragment,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from "react";
import { useFormatter, useTranslations } from "next-intl";
import {
  Card,
  Dropdown,
  SelectButton,
  MessageCard,
  Text,
} from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgClock } from "@opal/icons";
import { LineLoader } from "@opal/loaders";
import { clickOnKeyDown, cn } from "@opal/utils";
import type { RichStr } from "@opal/types";
import { useCCPairThroughput } from "@/lib/connectors/ccPair/hooks";
import type { ThroughputData } from "@/lib/connectors/hooks";
import type {
  CCPairThroughputResponse,
  CCPairThroughputSliceRun,
  CCPairThroughputWindow,
} from "@/lib/connectors/types";

// Re-exported for the chart's tests, which import it from here.
export { binsForWidth } from "@/lib/connectors/throughput";

const BARS_HEIGHT = 48;
const DAY_MINUTES = 1440;
const HOUR_MINUTES = 60;

// Labels sit on local times divisible by this. At a day they fall on midnight and show the date.
// All time has no fixed length, so it takes a spacing from its span.
const TICK_MINUTES = {
  "1h": 10,
  "24h": 4 * HOUR_MINUTES,
  "7d": DAY_MINUTES,
  all: null,
} satisfies Record<CCPairThroughputWindow, number | null>;

// All time labels the coarsest of these that still fits this many labels.
const SPAN_TICK_MINUTES = [
  1,
  5,
  10,
  30,
  HOUR_MINUTES,
  2 * HOUR_MINUTES,
  4 * HOUR_MINUTES,
  DAY_MINUTES,
  2 * DAY_MINUTES,
  7 * DAY_MINUTES,
  14 * DAY_MINUTES,
  30 * DAY_MINUTES,
];
const SPAN_TICKS_WANTED = 3;

/** Tick spacing for a span of any length, such as all time, so it keeps a few labels. */
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
export const PAIR_WINDOWS: readonly PickerWindow[] = ["24h", "7d", "all"];
/** The window a pair's chart and run lists open on. */
export const DEFAULT_PAIR_WINDOW: PickerWindow = "24h";

/** Each window's label under `admin.connector.runs.window`. */
export const WINDOW_LABEL_KEYS = {
  "1h": "h1",
  "24h": "h24",
  "7d": "d7",
  all: "all",
} as const satisfies Record<PickerWindow, string>;

function windowLabelKey(window: PickerWindow) {
  return WINDOW_LABEL_KEYS[window];
}

const WINDOW_HOURS = {
  "1h": 1,
  "24h": 24,
  "7d": 24 * 7,
  all: null,
} satisfies Record<PickerWindow, number | null>;

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

/** The window's start, or `null` for all time. */
export function pickedWindowStart({ window }: PickedWindow): string | null {
  const hours = WINDOW_HOURS[window];
  return hours === null ? null : windowStart(hours);
}

/** A chart slice or dragged span, as ISO times, that narrows the chart's run lists. `until` is exclusive. */
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

const DAY_LABEL_FORMAT = { month: "short", day: "numeric" } as const;
const TIME_LABEL_FORMAT = {
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
} as const;
const SLICE_TIME_FORMAT = {
  ...DAY_LABEL_FORMAT,
  ...TIME_LABEL_FORMAT,
} as const;

type Formatter = ReturnType<typeof useFormatter>;

/** The browser's time zone. The ticks fall on its local times, while next-intl formats in the server's zone. */
function localTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

/** A slice or picked span in local time, such as "Oct 21, 09:00 – 09:20". */
export function formatSliceRange(
  format: Formatter,
  from: Date,
  to: Date
): string {
  return format.dateTimeRange(from, to, {
    ...SLICE_TIME_FORMAT,
    timeZone: localTimeZone(),
  });
}

/** An axis label in local time: the date for day spacing, else the time. */
export function formatTickLabel(
  format: Formatter,
  value: number,
  tickMinutes: number
): string {
  return format.dateTime(new Date(value), {
    ...(tickMinutes >= DAY_MINUTES ? DAY_LABEL_FORMAT : TIME_LABEL_FORMAT),
    timeZone: localTimeZone(),
  });
}

/** The local times inside the window that are a whole multiple of `minutes` past local midnight, or every `minutes / DAY_MINUTES`th local midnight. */
function axisTicks(start: number, end: number, minutes: number): number[] {
  // Ticks within an hour step by their own spacing, longer ones hour by hour so a day's ticks still land on midnight across a clock change.
  const step = Math.min(minutes, HOUR_MINUTES);
  const everyDays = Math.max(1, minutes / DAY_MINUTES);
  const tick = new Date(start);
  tick.setSeconds(0, 0);
  tick.setMinutes(tick.getMinutes() - (tick.getMinutes() % step));
  const ticks: number[] = [];
  for (; tick.getTime() <= end; tick.setMinutes(tick.getMinutes() + step)) {
    const sinceMidnight = tick.getHours() * HOUR_MINUTES + tick.getMinutes();
    if (tick.getTime() < start || sinceMidnight % minutes !== 0) continue;
    // Days since the epoch by local date, so multi-day labels hold their dates as the window moves and across a clock change.
    const day =
      Date.UTC(tick.getFullYear(), tick.getMonth(), tick.getDate()) /
      (DAY_MINUTES * 60_000);
    if (day % everyDays === 0) ticks.push(tick.getTime());
  }
  return ticks;
}

// A few documents would otherwise fill the chart's height.
const Y_FLOOR = 100;

/** The top of the y scale: the highest bin, or `Y_FLOOR` when every bin is below it. */
export function yScaleMax(docsPerBin: number[]): number {
  return Math.max(Y_FLOOR, ...docsPerBin);
}

/** A status line's run kind. Only running and failed runs draw a line; every other status draws none. */
type StatusLineKind = "running" | "failed" | "resolved";

const LINE_KINDS: readonly StatusLineKind[] = ["running", "failed", "resolved"];

const LINE_CLASS = {
  running: "bg-chart-sequential-mass-02-blue",
  failed: "bg-chart-diverging-neg-10-red",
  resolved: "bg-chart-diverging-neg-02-red",
} satisfies Record<StatusLineKind, string>;

function isOfKind(run: CCPairThroughputSliceRun, kind: StatusLineKind) {
  switch (kind) {
    case "running":
      return run.status === "in_progress";
    case "failed":
      return run.status === "failed" && !run.resolved;
    case "resolved":
      return run.status === "failed" && run.resolved;
  }
}

interface Slice {
  from: number;
  to: number;
  docs: number;
  runs: CCPairThroughputSliceRun[];
  /** The attempt ids each status line draws. */
  lines: Record<StatusLineKind, number[]>;
}

function toSlice(
  from: number,
  to: number,
  docs: number,
  runs: CCPairThroughputSliceRun[]
): Slice {
  const idsOf = (kind: StatusLineKind) =>
    runs.filter((run) => isOfKind(run, kind)).map((run) => run.attempt_id);
  return {
    from,
    to,
    docs,
    runs,
    lines: {
      running: idsOf("running"),
      failed: idsOf("failed"),
      resolved: idsOf("resolved"),
    },
  };
}

/** The response's slices, or equal slices of its flat counts, without runs, from an API a deploy behind. */
function slicesOf(data: CCPairThroughputResponse): Slice[] {
  if (data.slices !== undefined) {
    return data.slices.map((slice) =>
      toSlice(
        Date.parse(slice.start),
        Date.parse(slice.end),
        slice.docs_indexed,
        slice.runs
      )
    );
  }
  const start = Date.parse(data.window_start);
  const sliceMs =
    (Date.parse(data.window_end) - start) / data.docs_indexed.length;
  return data.docs_indexed.map((docs, index) =>
    toSlice(start + index * sliceMs, start + (index + 1) * sliceMs, docs, [])
  );
}

/** A slice in local time, such as "Oct 21, 09:00 – 09:20". */
function formatSlice(format: Formatter, slice: Slice): string {
  return formatSliceRange(format, new Date(slice.from), new Date(slice.to));
}

/** The line's runs that began in its slice. A run is in every slice it spans, so one also in the slice before began earlier. */
function startedIn(
  slices: Slice[],
  index: number,
  kind: StatusLineKind
): number[] {
  const slice = slices[index];
  if (slice === undefined) return [];
  const earlier = new Set(slices[index - 1]?.runs.map((run) => run.attempt_id));
  return slice.lines[kind].filter((id) => !earlier.has(id));
}

/** The one line kind a slice draws, or null when it draws none or several. */
function slotKind(slice: Slice): StatusLineKind | null {
  const kinds = LINE_KINDS.filter((kind) => slice.lines[kind].length > 0);
  return kinds.length === 1 ? (kinds[0] ?? null) : null;
}

/** Open runs that completed with errors: the tooltip's errors count runs, not document errors. */
function openErrorCount(slice: Slice): number {
  return slice.runs.filter(
    (run) => run.status === "completed_with_errors" && !run.resolved
  ).length;
}

/** The first slice holding the attempt, or null when none does. */
function firstSliceWith(slices: Slice[], attemptId: number | null) {
  if (attemptId === null) return null;
  const index = slices.findIndex((slice) =>
    slice.runs.some((run) => run.attempt_id === attemptId)
  );
  return index === -1 ? null : index;
}

/** A status line under the pointer, with the runs of its kind that began in its slice. */
export interface HoveredLine {
  kind: StatusLineKind;
  attemptIds: number[];
}

/** A bar or a status line, by its slice. */
interface Mark {
  index: number;
  kind: StatusLineKind | "bar";
}

/** The bar or status line an event landed on, from its slot's data attributes. */
function markAt(target: EventTarget): Mark | null {
  if (!(target instanceof Element)) return null;
  const slot = target.closest<HTMLElement>("[data-slice]");
  if (slot === null) return null;
  const kind =
    slot.dataset.line === undefined
      ? "bar"
      : LINE_KINDS.find((each) => each === slot.dataset.line);
  const index = Number(slot.dataset.slice);
  return kind === undefined || Number.isNaN(index) ? null : { index, kind };
}

/** `part` of `whole` as a fraction, 0 for an empty whole. */
function fractionOf(part: number, whole: number): number {
  return whole > 0 ? part / whole : 0;
}

/** `part` of `whole` as a CSS percentage, 0 for an empty whole. */
function percentOf(part: number, whole: number): string {
  return `${fractionOf(part, whole) * 100}%`;
}

export interface ThroughputWindowPickerProps<W extends PickerWindow> {
  windows: readonly W[];
  value: W;
  onChange: (window: W) => void;
  /** A span picked on the chart. The picker shows it in place of the window, with an X that calls `onClearSelection`. */
  selection?: SliceRange | null;
  onClearSelection?: () => void;
  /** Shown instead of the window's name, for a list that widened past it. */
  label?: string;
}

/** Picks how far back a throughput chart, and any list that shares it, reaches, and shows the span picked inside it. */
export function ThroughputWindowPicker<W extends PickerWindow>({
  windows,
  value,
  onChange,
  selection = null,
  onClearSelection,
  label,
}: ThroughputWindowPickerProps<W>) {
  const t = useTranslations("admin.connector.statusCard.throughput");
  const tWindow = useTranslations("admin.connector.runs.window");
  const format = useFormatter();
  return (
    <Dropdown>
      <Dropdown.Trigger asChild>
        {selection === null || onClearSelection === undefined ? (
          <SelectButton chevron icon={SvgClock} state="empty">
            {label ?? tWindow(windowLabelKey(value))}
          </SelectButton>
        ) : (
          // The span takes the picker's place, so the row keeps its shape. Its X returns to the window.
          <SelectButton
            variant="select-filter"
            chevron
            labelFont="main-ui-action"
            icon={SvgClock}
            state="selected"
            tooltip={t("rangeFilter")}
            onClear={onClearSelection}
          >
            {formatSliceRange(
              format,
              new Date(selection.since),
              new Date(selection.until)
            )}
          </SelectButton>
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

interface TooltipCardProps {
  title: string | RichStr;
  slice: Slice;
}

/** The small card over a bar or a status line: what it counts, then its slice's time range. */
function TooltipCard({ title, slice }: TooltipCardProps) {
  const format = useFormatter();
  return (
    <Card border="solid" rounding={2} padding={1}>
      <Text font="secondary-action" color="text-04">
        {title}
      </Text>
      <Text font="secondary-body" color="text-03">
        {formatSlice(format, slice)}
      </Text>
    </Card>
  );
}

interface CenteredInsideProps {
  /** Where its middle sits across its parent's width, from 0 to 1. */
  at: number;
  className?: string;
  children: ReactNode;
}

/** Centered at `at` across its positioned parent, and moved inward where it would cross either edge, since the chart's card clips what hangs past it. Placed by CSS alone, since feeding a measured width back into the position can re-render without end. */
function CenteredInside({ at, className, children }: CenteredInsideProps) {
  return (
    // raw-ok: the widest span centered on `at` that fits the parent, which Section cannot position
    <div
      // rtl past the middle, so content wider than the span overflows toward the far edge. Physical insets, since dir would flip logical ones.
      dir={at > 0.5 ? "rtl" : "ltr"}
      className={cn("absolute", className)}
      style={{
        left: `${Math.max(0, 2 * at - 1) * 100}%`,
        right: `${Math.max(0, 1 - 2 * at) * 100}%`,
      }}
    >
      {/* raw-ok: auto margins center it while it fits and resolve to zero once it does not */}
      <div dir="ltr" className="mx-auto w-max">
        {children}
      </div>
    </div>
  );
}

/** A run of slices by index, inclusive, as a drag covers them or a selection overlaps them. */
interface SliceSpan {
  from: number;
  to: number;
}

function ordered({ from, to }: SliceSpan): SliceSpan {
  return { from: Math.min(from, to), to: Math.max(from, to) };
}

function selectedSlices(
  slices: Slice[],
  selection: SliceRange | null
): SliceSpan | null {
  if (selection === null) return null;
  const since = Date.parse(selection.since);
  const until = Date.parse(selection.until);
  const inside = slices.flatMap((slice, index) =>
    slice.to > since && slice.from < until ? [index] : []
  );
  const from = inside[0];
  const to = inside[inside.length - 1];
  return from === undefined || to === undefined ? null : { from, to };
}

/** How a chart links to the page around it. */
interface ThroughputLinkProps {
  /** The brushed span. Every bar still draws, and those outside it fade. */
  selection?: SliceRange | null;
  /** A click picks one slice and a drag a span. A click on the one picked slice clears it with null. */
  onRangeSelect?: (range: SliceRange | null) => void;
  /** A click on a failure line, with the first open failed run of its slice. */
  onFocusAttempt?: (attemptId: number) => void;
  /** An activity hovered elsewhere on the page: its lines stay, the others fade, and a dashed guide marks its first slice. */
  hoveredAttemptId?: number | null;
  /** The status line under the pointer, or null once it leaves the lines. */
  onHoverLine?: (line: HoveredLine | null) => void;
}

/** The links a chart keeps with the activity panel beside it. */
export type ThroughputActivityLinks = Pick<
  ThroughputLinkProps,
  "hoveredAttemptId" | "onFocusAttempt" | "onHoverLine"
>;

export interface ThroughputBarsProps extends ThroughputLinkProps {
  data: CCPairThroughputResponse;
  range: CCPairThroughputWindow;
  /** The bars' height in pixels, above the axis. */
  height?: number;
}

// Plain DOM, not recharts: recharts 3 remounts every bar on each render, so a press between pointer down and up lands on a detached node.
/** Documents indexed in each slice of a window, over three status lines per slice for its running, failed and resolved failed runs. */
export function ThroughputBars({
  data,
  range,
  height = BARS_HEIGHT,
  selection = null,
  onRangeSelect,
  onFocusAttempt,
  hoveredAttemptId = null,
  onHoverLine,
}: ThroughputBarsProps) {
  const t = useTranslations("admin.connector.statusCard.throughput");
  const format = useFormatter();
  const [drag, setDrag] = useState<SliceSpan | null>(null);
  const [tip, setTip] = useState<Mark | null>(null);
  // The one bar in the tab order; arrow keys move it.
  const [focusable, setFocusable] = useState(0);
  const barRefs = useRef<(HTMLDivElement | null)[]>([]);
  // The release already picked, so the click that follows it must not pick again.
  const releasePicked = useRef(false);
  const start = Date.parse(data.window_start);
  const end = Date.parse(data.window_end);
  const slices = useMemo(() => slicesOf(data), [data]);
  const barLabels = useMemo(
    () =>
      slices.map((slice) =>
        t("barLabel", { count: slice.docs, range: formatSlice(format, slice) })
      ),
    [slices, t, format]
  );
  const count = slices.length;
  // The bar count follows the width, so a stop past the last bar falls back to it.
  const stop = Math.min(focusable, count - 1);
  const top = yScaleMax(slices.map((slice) => slice.docs));
  const tickMinutes = TICK_MINUTES[range] ?? spanTickMinutes(end - start);
  // A tick on the window's edge would hang its label off the chart.
  // Memoized: hover and drag re-render the chart, and all time steps hour by hour.
  const ticks = useMemo(
    () =>
      axisTicks(start, end, tickMinutes).filter(
        (tick) => tick > start && tick < end
      ),
    [start, end, tickMinutes]
  );
  const dragged = drag === null ? null : ordered(drag);
  const brush = dragged ?? selectedSlices(slices, selection);
  // An activity outside the window links to nothing, so nothing fades.
  const held = firstSliceWith(slices, hoveredAttemptId);
  const tipped =
    tip === null ? null : { ...tip, slice: slices[tip.index] ?? null };

  function fadesLine(runs: number[]): boolean {
    return (
      held !== null &&
      hoveredAttemptId !== null &&
      !runs.includes(hoveredAttemptId)
    );
  }
  function markTitle(kind: Mark["kind"], slice: Slice): string {
    if (kind === "bar") return t("tooltip", { count: slice.docs });
    return t("lineTooltip", {
      failures: slice.lines.failed.length,
      errors: openErrorCount(slice),
    });
  }

  /** The slot at the pointer's x: the browser holds a touch pointer on the element it began on, so x, not the element under the finger, picks the slot. With no layout (width 0) the slot the event landed on. */
  function sliceAt(event: PointerEvent<HTMLDivElement>): number | null {
    if (count === 0) return null;
    const rect = event.currentTarget.getBoundingClientRect();
    const index = Math.floor(
      ((event.clientX - rect.left) / rect.width) * count
    );
    if (Number.isFinite(index)) return Math.min(count - 1, Math.max(0, index));
    return markAt(event.target)?.index ?? null;
  }
  // Picking the one picked slice again clears it.
  function pickSpan({ from, to }: SliceSpan) {
    const first = slices[from];
    const last = slices[to];
    if (
      onRangeSelect === undefined ||
      first === undefined ||
      last === undefined
    )
      return;
    const repeated =
      from === to &&
      selection !== null &&
      Date.parse(selection.since) === first.from &&
      Date.parse(selection.until) === last.to;
    onRangeSelect(
      repeated
        ? null
        : {
            since: new Date(first.from).toISOString(),
            until: new Date(last.to).toISOString(),
          }
    );
  }
  // The drag ends on release or when the pointer leaves the bars, and picks what it covered.
  function endDrag() {
    if (dragged === null) return;
    setDrag(null);
    pickSpan(dragged);
  }

  function showTip(mark: Mark | null) {
    if (mark?.index === tip?.index && mark?.kind === tip?.kind) return;
    setTip(mark);
    if (mark !== null && mark.kind !== "bar") {
      onHoverLine?.({
        kind: mark.kind,
        attemptIds: startedIn(slices, mark.index, mark.kind),
      });
    } else if (tip !== null && tip.kind !== "bar") {
      onHoverLine?.(null);
    }
  }
  // A blur clears only its own tooltip, so it leaves one the pointer has since opened.
  function hideTip(mark: Mark) {
    if (tip?.index === mark.index && tip.kind === mark.kind) showTip(null);
  }
  function focusFailure(slice: Slice) {
    const attemptId = slice.lines.failed[0];
    if (attemptId !== undefined) onFocusAttempt?.(attemptId);
  }
  function barKeyDown(event: KeyboardEvent<HTMLDivElement>, index: number) {
    const step =
      event.key === "ArrowLeft" ? -1 : event.key === "ArrowRight" ? 1 : 0;
    if (step === 0) {
      clickOnKeyDown(() => pickSpan({ from: index, to: index }))(event);
      return;
    }
    event.preventDefault();
    barRefs.current[index + step]?.focus();
  }
  // The failed line is a button that focuses its run, with the tooltip on keyboard focus too. A run spans slices, so only the slice it began in is a tab stop.
  function failedLineProps(slice: Slice, index: number) {
    const mark: Mark = { index, kind: "failed" };
    return {
      role: "button",
      tabIndex: startedIn(slices, index, "failed").length > 0 ? 0 : -1,
      "aria-label": markTitle("failed", slice),
      onClick: () => focusFailure(slice),
      onKeyDown: clickOnKeyDown(() => focusFailure(slice)),
      onFocus: () => showTip(mark),
      onBlur: () => hideTip(mark),
    };
  }

  // The hover and click target of a status line, with the attributes markAt reads.
  function lineTargetProps(kind: StatusLineKind, slice: Slice, index: number) {
    return {
      "data-testid": "chart-status-line",
      "data-slice": index,
      "data-line": kind,
      className: cn("flex-1", kind === "failed" && "cursor-pointer"),
      ...(kind === "failed" && failedLineProps(slice, index)),
    };
  }

  return (
    // Time runs left to right in every locale, so the whole chart stays ltr.
    <Section
      alignItems="stretch"
      gap={0.5}
      height="fit"
      dir="ltr"
      className="relative"
      onPointerOver={(event) => showTip(markAt(event.target))}
      onPointerLeave={() => showTip(null)}
    >
      {tipped !== null && tipped.slice !== null && (
        <CenteredInside
          at={fractionOf(tipped.index + 0.5, count)}
          className="pointer-events-none bottom-full z-10 mb-1"
        >
          <TooltipCard
            title={markTitle(tipped.kind, tipped.slice)}
            slice={tipped.slice}
          />
        </CenteredInside>
      )}
      <Section alignItems="stretch" gap={0} height="fit">
        <Section
          role="group"
          aria-label={t("ariaLabel")}
          flexDirection="row"
          alignItems="stretch"
          gap={0}
          height={height / 16}
          // A sideways touch swipe drags the brush, while a vertical one still scrolls.
          className={cn(
            "relative touch-pan-y select-none border-b border-border-01",
            onRangeSelect !== undefined && "cursor-pointer"
          )}
          onPointerDown={(event) => {
            const index = sliceAt(event);
            // Only the primary button drags.
            if (
              onRangeSelect === undefined ||
              event.button > 0 ||
              index === null
            )
              return;
            setDrag({ from: index, to: index });
          }}
          onPointerMove={(event) => {
            const index = sliceAt(event);
            if (drag === null || index === null || index === drag.to) return;
            setDrag({ from: drag.from, to: index });
          }}
          onPointerUp={() => {
            releasePicked.current = dragged !== null;
            endDrag();
          }}
          onPointerLeave={endDrag}
          onClick={() => {
            releasePicked.current = false;
          }}
          onPointerCancel={() => setDrag(null)}
        >
          {brush !== null && (
            // raw-ok: the brush background spans its slots behind the bars
            <div
              className="absolute inset-y-0 bg-chart-category-blue-1-05"
              style={{
                insetInlineStart: percentOf(brush.from, count),
                width: percentOf(brush.to - brush.from + 1, count),
              }}
            />
          )}
          {slices.map((slice, index) => {
            const faded =
              brush !== null && (index < brush.from || index > brush.to);
            const mark: Mark = { index, kind: "bar" };
            return (
              // One slot per slice, which takes the pointer even with no bar and draws the focus ring, since a bar can be 0px tall.
              // Keyed by position: all-time slice bounds move on every poll, and a remounted bar would drop keyboard focus.
              <Section
                key={index}
                data-slice={index}
                flexDirection="row"
                alignItems="end"
                gap={0}
                width="auto"
                className="relative flex-1 hover:bg-background-tint-02 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-inset has-[:focus-visible]:ring-border-04"
              >
                {/* raw-ok: a bar sized to its count, below every Opal size step */}
                <div
                  ref={(element) => {
                    barRefs.current[index] = element;
                  }}
                  data-testid="chart-bar"
                  role="button"
                  tabIndex={index === stop ? 0 : -1}
                  aria-label={barLabels[index]}
                  onFocus={() => {
                    setFocusable(index);
                    showTip(mark);
                  }}
                  onBlur={() => hideTip(mark)}
                  onKeyDown={(event) => barKeyDown(event, index)}
                  // Screen readers activate a button with a bare click and no pointer events.
                  onClick={() => {
                    if (!releasePicked.current)
                      pickSpan({ from: index, to: index });
                  }}
                  className={cn(
                    "w-[58%] rounded-[1px] bg-chart-category-blue-1 outline-hidden",
                    faded && "opacity-50"
                  )}
                  style={{ height: percentOf(slice.docs, top) }}
                />
              </Section>
            );
          })}
          {held !== null && (
            // raw-ok: a 1px guide over the bars, below every Opal size step
            <div
              className="pointer-events-none absolute inset-y-0 border-s border-dashed border-border-03"
              style={{ insetInlineStart: percentOf(held + 0.5, count) }}
            />
          )}
        </Section>
        <Section height={1} className="relative" aria-hidden>
          {ticks.map((tick) => {
            const at = fractionOf(tick - start, end - start);
            return (
              <Fragment key={tick}>
                {/* raw-ok: a 2px tick mark at its time, which Section cannot position */}
                <div
                  className="absolute top-0 h-0.5 w-px -translate-x-1/2 bg-border-01"
                  style={{
                    insetInlineStart: percentOf(tick - start, end - start),
                  }}
                />
                <CenteredInside at={at} className="top-1">
                  {/* raw-ok: DM Mono at 10px has no Text preset */}
                  <span className="block whitespace-nowrap text-[10px] leading-3 text-text-03 [font-family:var(--font-dm-mono)]">
                    {formatTickLabel(format, tick, tickMinutes)}
                  </span>
                </CenteredInside>
              </Fragment>
            );
          })}
        </Section>
      </Section>
      <Section flexDirection="row" gap={0} height={0.625}>
        {slices.map((slice, index) => {
          const single = slotKind(slice);
          return (
            // Three thirds per slot, each line centered in its own. The line's third takes the pointer, or the whole slot when it holds one kind.
            <Section
              key={index}
              flexDirection="row"
              gap={0}
              width="auto"
              className="flex-1"
              {...(single !== null && lineTargetProps(single, slice, index))}
            >
              {LINE_KINDS.map((kind) => {
                const runs = slice.lines[kind];
                if (runs.length === 0) {
                  return <Section key={kind} width="auto" className="flex-1" />;
                }
                return (
                  <Section
                    key={kind}
                    width="auto"
                    className="flex-1"
                    {...(single === null &&
                      lineTargetProps(kind, slice, index))}
                  >
                    {/* raw-ok: a 1.5px line, below every Opal size step */}
                    <div
                      className={cn(
                        "h-full w-[1.5px] rounded-[2px]",
                        LINE_CLASS[kind],
                        fadesLine(runs) && "opacity-25"
                      )}
                    />
                  </Section>
                );
              })}
            </Section>
          );
        })}
      </Section>
    </Section>
  );
}

/** The window holds no run and indexed no documents. */
export function isEmptyThroughput(data: CCPairThroughputResponse): boolean {
  return data.runs.length === 0 && data.docs_indexed.every((n) => n === 0);
}

export interface ThroughputChartViewProps extends ThroughputLinkProps {
  /** The response its caller polls, so the caller can read it too. */
  throughput: ThroughputData<CCPairThroughputResponse>;
  range: CCPairThroughputWindow;
}

/** A pair's throughput over the window, measured and fetched by the caller, with its loading and error states. */
export function ThroughputChartView({
  throughput: { ref, data, error, stale },
  range,
  ...links
}: ThroughputChartViewProps) {
  const t = useTranslations("admin.connector.statusCard.throughput");
  let body: ReactNode;
  if (error !== undefined) {
    body = <MessageCard variant="error" title={t("loadError")} />;
  } else if (data === undefined) {
    body = <LineLoader lines={3} />;
  } else {
    body = (
      <ThroughputBars
        data={data}
        range={range}
        {...links}
        // The dimmed bars are the old window's, so they pick nothing until the new one lands.
        onRangeSelect={stale ? undefined : links.onRangeSelect}
      />
    );
  }
  return (
    // Measured before the first fetch, and kept, dimmed, while a new bar count or window loads.
    <Section
      ref={ref}
      alignItems="stretch"
      height="fit"
      className={cn(stale && "opacity-50")}
    >
      {body}
    </Section>
  );
}

export interface ThroughputChartProps extends ThroughputLinkProps {
  ccPairId: number;
  range: CCPairThroughputWindow;
}

/** One pair's throughput over the window, polled, in as many bars as its width fits. */
export default function ThroughputChart({
  ccPairId,
  range,
  ...links
}: ThroughputChartProps) {
  const throughput = useCCPairThroughput(ccPairId, range);
  return (
    <ThroughputChartView throughput={throughput} range={range} {...links} />
  );
}
