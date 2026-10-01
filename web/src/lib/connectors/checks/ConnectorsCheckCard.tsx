"use client";

import { useMemo, useState, type Ref } from "react";
import { Content } from "@opal/layouts";
import * as GeneralLayouts from "@/layouts/general-layouts";
import { useFormatter, useTranslations } from "next-intl";
import { Button, Card, Divider, Tag, Text } from "@opal/components";
import {
  SvgAlertCircle,
  SvgCheckCircle,
  SvgChevronDown,
  SvgChevronRight,
  SvgClock,
  SvgCircle,
  SvgExpand,
  SvgFold,
  SvgLoader,
  SvgMinusCircle,
  SvgPauseCircle,
  SvgRefreshCw,
  SvgXCircle,
} from "@opal/icons";
import type { IconFunctionComponent, IconProps } from "@opal/types";
import type { TextColor } from "@onyx-ai/shared/contracts";
import { cn } from "@opal/utils";
import {
  applicableCheckCount,
  countCheckStates,
  rowsFromDraft,
  rowsFromReport,
  summarizeCheckStates,
  type CheckRowModel,
} from "@/lib/connectors/checks/checkRows";
import type {
  CapabilityReportSnapshot,
  DraftCheckRunSnapshot,
  DraftCheckState,
} from "@/lib/connectors/checks/types";

interface ConnectorsCheckCardBaseProps {
  /** True while the first fetch is pending. */
  loading?: boolean;
  /** True from a run request until the run settles. */
  running?: boolean;
  onRerun?: () => void;
  /** Draws the border in a status color to pull the admin's eye. */
  highlighted?: boolean;
  /** Config field name to its form label, for "Waiting for: …". */
  fieldLabels?: Record<string, string>;
  ref?: Ref<HTMLDivElement>;
}

interface ReportCardProps extends ConnectorsCheckCardBaseProps {
  /** The stored report row; `null` when no run has happened yet. */
  snapshot: CapabilityReportSnapshot | null;
  draft?: never;
}

interface DraftCardProps extends ConnectorsCheckCardBaseProps {
  /** The latest draft run of an unsaved form; `null` before the first run. */
  draft: DraftCheckRunSnapshot | null;
  snapshot?: never;
}

export type ConnectorsCheckCardProps = ReportCardProps | DraftCardProps;

// ---------------------------------------------------------------------------
// Status presentation
// ---------------------------------------------------------------------------

type CheckGroupKey =
  | "failed"
  | "indeterminate"
  | "inProgress"
  | "waiting"
  | "passed"
  | "skipped"
  | "notApplicable";

/** Group order: what blocks first, what is unknown or unfinished next, then
 * the rest. Not-applicable checks come last, folded. */
const GROUP_ORDER: readonly CheckGroupKey[] = [
  "failed",
  "indeterminate",
  "inProgress",
  "waiting",
  "passed",
  "skipped",
  "notApplicable",
];

const GROUP_OF_STATE: Record<DraftCheckState, CheckGroupKey> = {
  failed: "failed",
  indeterminate: "indeterminate",
  running: "inProgress",
  pending: "inProgress",
  waiting: "waiting",
  passed: "passed",
  skipped: "skipped",
  not_applicable: "notApplicable",
};

const GROUP_LABEL_KEYS = {
  failed: "groups.failed",
  indeterminate: "groups.indeterminate",
  inProgress: "groups.inProgress",
  waiting: "groups.waiting",
  passed: "groups.passed",
  skipped: "groups.skipped",
  notApplicable: "groups.notApplicable",
} as const satisfies Record<CheckGroupKey, string>;

/** Detail shown when the backend sends no message for the state. */
const DETAIL_FALLBACK_KEYS = {
  failed: "status.failed",
  indeterminate: "status.indeterminate",
  passed: "status.passed",
  skipped: "status.skipped",
  running: "status.running",
  pending: "status.pending",
  waiting: "status.waiting",
  not_applicable: "status.notApplicable",
} as const satisfies Record<DraftCheckState, string>;

function SpinningLoader({ className, ...props }: IconProps) {
  return <SvgLoader className={cn("animate-spin", className)} {...props} />;
}

const STATUS_ICONS: Record<
  DraftCheckState,
  { icon: IconFunctionComponent; className: string }
> = {
  failed: { icon: SvgXCircle, className: "stroke-status-error-05" },
  indeterminate: {
    icon: SvgAlertCircle,
    className: "stroke-status-warning-05",
  },
  passed: { icon: SvgCheckCircle, className: "stroke-status-success-05" },
  skipped: { icon: SvgMinusCircle, className: "stroke-text-03" },
  running: { icon: SpinningLoader, className: "stroke-text-03" },
  pending: { icon: SvgClock, className: "stroke-text-03" },
  waiting: { icon: SvgPauseCircle, className: "stroke-text-03" },
  not_applicable: { icon: SvgCircle, className: "stroke-text-02" },
};

const DETAIL_COLORS: Record<DraftCheckState, TextColor> = {
  failed: "status-error-05",
  indeterminate: "text-04",
  passed: "text-05",
  skipped: "text-03",
  running: "text-03",
  pending: "text-03",
  waiting: "text-03",
  not_applicable: "text-03",
};

// ---------------------------------------------------------------------------
// ProgressRing — passed and failed shares of the total, as arcs
// ---------------------------------------------------------------------------

interface ProgressRingProps extends Pick<IconProps, "className"> {
  passed: number;
  failed: number;
  total: number;
}

function ProgressRing({ passed, failed, total, className }: ProgressRingProps) {
  const size = 20;
  const strokeWidth = 2.5;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const arc = (count: number) =>
    total === 0 ? 0 : (count / total) * circumference;
  const passedArc = arc(passed);
  const failedArc = arc(failed);
  const shared = {
    cx: size / 2,
    cy: size / 2,
    r: radius,
    strokeWidth,
    fill: "none",
  };

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      className={cn("shrink-0 -rotate-90", className)}
      aria-hidden
    >
      <circle {...shared} className="stroke-border-02" />
      {passedArc > 0 && (
        <circle
          {...shared}
          className="stroke-status-success-05"
          strokeDasharray={`${passedArc} ${circumference - passedArc}`}
        />
      )}
      {failedArc > 0 && (
        <circle
          {...shared}
          className="stroke-status-error-05"
          strokeDasharray={`${failedArc} ${circumference - failedArc}`}
          strokeDashoffset={-passedArc}
        />
      )}
    </svg>
  );
}

// ---------------------------------------------------------------------------
// CheckRow
// ---------------------------------------------------------------------------

interface CheckRowProps {
  result: CheckRowModel;
  fieldLabels?: Record<string, string>;
}

function CheckRow({ result, fieldLabels }: CheckRowProps) {
  const t = useTranslations("admin.connectorChecks");
  const format = useFormatter();
  const { icon: StatusIcon, className: iconClassName } =
    STATUS_ICONS[result.state];
  // A failed required check blocks the capability, so the row stands out.
  const blocking = result.state === "failed" && result.required;
  // A waiting check names the form fields it needs, by their form labels.
  const detail =
    result.state === "waiting" && result.waiting_for.length > 0
      ? t("waiting.fields", {
          fields: format.list(
            result.waiting_for.map((name) => fieldLabels?.[name] ?? name),
            { type: "conjunction" }
          ),
        })
      : result.message || t(DETAIL_FALLBACK_KEYS[result.state]);
  // Failures and unverified checks carry the detail an admin acts on, so their
  // rows expand to the full message, the fix, and the docs link.
  const expandable =
    (result.state === "failed" || result.state === "indeterminate") &&
    (result.message !== "" ||
      result.remediation !== null ||
      result.docs_link !== null);
  // A blocking failure opens on its own; the admin must act on it.
  const [expanded, setExpanded] = useState(blocking);
  const ChevronIcon = expanded ? SvgChevronDown : SvgChevronRight;

  const summary = (
    <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)_auto] items-center gap-4">
      <div className="flex min-w-0 items-center gap-3">
        <StatusIcon size={20} className={cn("shrink-0", iconClassName)} />
        <Text font="main-ui-action" color="text-04" maxLines={1}>
          {result.display_name}
        </Text>
      </div>

      <div className="flex min-w-0 items-center gap-2">
        {!expanded && (
          <Text
            font="main-ui-body"
            color={DETAIL_COLORS[result.state]}
            maxLines={1}
          >
            {detail}
          </Text>
        )}
      </div>

      <div className="flex items-center gap-2 justify-self-end">
        {result.required &&
          (blocking ? (
            <Tag title={t("required.label")} color="gray" />
          ) : (
            <Text font="main-ui-body" color="text-03">
              {t("required.label")}
            </Text>
          ))}
        {expandable && (
          <ChevronIcon size={16} className="shrink-0 stroke-text-03" />
        )}
      </div>
    </div>
  );

  const details = expandable && expanded && (
    <div className="flex flex-col gap-2 pl-8 pt-2">
      <Text font="main-ui-body" color={DETAIL_COLORS[result.state]}>
        {detail}
      </Text>
      {result.remediation !== null && (
        <div className="flex flex-col gap-1">
          <Text font="secondary-action" color="text-04">
            {t("remediation.label")}
          </Text>
          <Text font="secondary-body" color="text-04">
            {result.remediation}
          </Text>
        </div>
      )}
      {result.docs_link !== null && (
        <a
          href={result.docs_link}
          target="_blank"
          rel="noopener noreferrer"
          className="w-fit underline"
        >
          <Text font="secondary-body" color="text-04">
            {t("docsLink.label")}
          </Text>
        </a>
      )}
    </div>
  );

  const row = expandable ? (
    <>
      <button
        type="button"
        className="w-full text-left"
        aria-expanded={expanded}
        aria-label={expanded ? t("details.hide") : t("details.show")}
        onClick={() => setExpanded((value) => !value)}
      >
        {summary}
      </button>
      {details}
    </>
  ) : (
    summary
  );

  return blocking ? (
    <Card color="status-error-00" rounding={3} padding={2} data-blocking>
      {row}
    </Card>
  ) : (
    <div className="p-2">{row}</div>
  );
}

// ---------------------------------------------------------------------------
// CheckGroup — one status, foldable
// ---------------------------------------------------------------------------

interface CheckGroupProps {
  group: CheckGroupKey;
  results: CheckRowModel[];
  fieldLabels?: Record<string, string>;
}

function CheckGroup({ group, results, fieldLabels }: CheckGroupProps) {
  const t = useTranslations("admin.connectorChecks");
  return (
    <Divider
      title={t(GROUP_LABEL_KEYS[group], { count: results.length })}
      foldable
      // Checks that do not apply are only context; they start folded.
      defaultOpen={group !== "notApplicable"}
    >
      <div className="flex flex-col">
        {results.map((result) => (
          <CheckRow
            key={result.check_id}
            result={result}
            fieldLabels={fieldLabels}
          />
        ))}
      </div>
    </Divider>
  );
}

// ---------------------------------------------------------------------------
// ConnectorsCheckCard
// ---------------------------------------------------------------------------

/**
 * The capability checks for one credential and connector, grouped by state
 * like a pull request's checks panel. It shows either a stored report (the
 * last completed run, under a spinner while a re-run is in flight) or a
 * draft run of an unsaved form, whose checks move through pending, running
 * and waiting states as the form fills in.
 */
export function ConnectorsCheckCard(props: ConnectorsCheckCardProps) {
  const {
    loading = false,
    running = false,
    onRerun,
    highlighted = false,
    fieldLabels,
    ref,
  } = props;
  const t = useTranslations("admin.connectorChecks");
  const format = useFormatter();
  const [collapsed, setCollapsed] = useState(false);

  const isDraft = props.draft !== undefined;
  const results = useMemo(
    () =>
      props.draft !== undefined
        ? rowsFromDraft(props.draft)
        : rowsFromReport(props.snapshot),
    [props.draft, props.snapshot]
  );
  const groups = useMemo(
    () =>
      GROUP_ORDER.map((group) => ({
        group,
        results: results.filter(
          (result) => GROUP_OF_STATE[result.state] === group
        ),
      })).filter((group) => group.results.length > 0),
    [results]
  );
  const counts = useMemo(() => countCheckStates(results), [results]);
  const passed = counts.passed;
  const failed = counts.failed;
  const total = applicableCheckCount(counts);
  const isRunning =
    running ||
    props.snapshot?.run_status === "running" ||
    props.draft?.status === "running";
  const hasReport = results.length > 0;

  // The counts as one comma-separated line in a fixed order, e.g.
  // "1 in progress, 2 more expected, 1 skipped, 4 successful". Zero counts
  // are left out.
  const summary = useMemo(() => {
    if (!hasReport) return isRunning ? t("running.label") : t("empty.label");
    return format.list(
      summarizeCheckStates(counts).map(({ slot, count }) =>
        t(`summary.${slot}`, { count })
      ),
      { type: "unit" }
    );
  }, [hasReport, isRunning, counts, t, format]);

  // Content wants an icon component; this one is the ring, or a spinner
  // while a run is in flight.
  const HeaderIcon = useMemo<IconFunctionComponent>(
    () =>
      function HeaderIcon({ className }: IconProps) {
        return (
          <ProgressRing
            passed={passed}
            failed={failed}
            total={total}
            className={className}
          />
        );
      },
    [passed, failed, total]
  );

  return (
    <Card
      ref={ref}
      border="solid"
      borderColor={highlighted ? (failed > 0 ? "error" : "info") : "default"}
      rounding={4}
      padding={2}
    >
      <div className="flex flex-col gap-3">
        <div className="flex items-start gap-3">
          <GeneralLayouts.Section
            padding={1}
            height="fit"
            alignItems="start"
            className="min-w-0 flex-1"
          >
            <Content
              icon={HeaderIcon}
              title={
                hasReport ? t("titleWithCount", { passed, total }) : t("title")
              }
              // A draft run changes while the admin types, so its summary
              // stays visible; a stored report shows it only when folded.
              description={collapsed || isDraft ? summary : undefined}
              sizePreset="section"
              variant="section"
            />
          </GeneralLayouts.Section>
          <div className="flex items-center">
            {onRerun && !collapsed && (
              <Button
                icon={SvgRefreshCw}
                prominence="internal"
                tooltip={t("rerunButton.label")}
                aria-label={t("rerunButton.label")}
                disabled={isRunning || loading}
                onClick={onRerun}
              />
            )}
            <Button
              icon={collapsed ? SvgExpand : SvgFold}
              prominence="internal"
              tooltip={
                collapsed ? t("foldButton.expand") : t("foldButton.fold")
              }
              aria-label={
                collapsed ? t("foldButton.expand") : t("foldButton.fold")
              }
              aria-expanded={!collapsed}
              onClick={() => setCollapsed((value) => !value)}
            />
          </div>
        </div>

        {!collapsed &&
          (hasReport ? (
            <div className="flex flex-col gap-2">
              {groups.map((group) => (
                <CheckGroup
                  key={group.group}
                  group={group.group}
                  results={group.results}
                  fieldLabels={fieldLabels}
                />
              ))}
            </div>
          ) : (
            <Text font="main-ui-body" color="text-03">
              {isRunning ? t("running.label") : t("empty.label")}
            </Text>
          ))}
      </div>
    </Card>
  );
}
