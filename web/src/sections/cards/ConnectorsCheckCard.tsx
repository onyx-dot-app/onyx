"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Card,
  Divider,
  IconLoader,
  Tag,
  Text,
  Tooltip,
} from "@opal/components";
import {
  SvgAlertCircle,
  SvgCheckCircle,
  SvgFold,
  SvgInfo,
  SvgMinusCircle,
  SvgRefreshCw,
  SvgXCircle,
} from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import type { TextColor } from "@onyx-ai/shared/contracts";
import { cn } from "@opal/utils";
import type {
  CapabilityCheckResult,
  CapabilityCheckStatus,
  CapabilityReportSnapshot,
} from "@/lib/connectors/checks/types";

export interface ConnectorsCheckCardProps {
  /** The stored report row; `null` when no run has happened yet. */
  snapshot: CapabilityReportSnapshot | null;
  /** True while the first fetch is pending. */
  loading?: boolean;
  /** True from a re-run request until the row reads `completed`. */
  running?: boolean;
  onRerun?: () => void;
}

// ---------------------------------------------------------------------------
// Status presentation
// ---------------------------------------------------------------------------

/** Group order: what blocks first, what is unknown next, then the rest. */
const GROUP_ORDER: readonly CapabilityCheckStatus[] = [
  "failed",
  "indeterminate",
  "passed",
  "skipped",
];

const GROUP_LABEL_KEYS = {
  failed: "groups.failed",
  indeterminate: "groups.indeterminate",
  passed: "groups.passed",
  skipped: "groups.skipped",
} as const satisfies Record<CapabilityCheckStatus, string>;

/** Detail shown when the backend sends no message for the outcome. */
const DETAIL_FALLBACK_KEYS = {
  failed: "status.failed",
  indeterminate: "status.indeterminate",
  passed: "status.passed",
  skipped: "status.skipped",
} as const satisfies Record<CapabilityCheckStatus, string>;

const STATUS_ICONS: Record<
  CapabilityCheckStatus,
  { icon: IconFunctionComponent; className: string }
> = {
  failed: { icon: SvgXCircle, className: "stroke-status-error-05" },
  indeterminate: {
    icon: SvgAlertCircle,
    className: "stroke-status-warning-05",
  },
  passed: { icon: SvgCheckCircle, className: "stroke-status-success-05" },
  skipped: { icon: SvgMinusCircle, className: "stroke-text-03" },
};

const DETAIL_COLORS: Record<CapabilityCheckStatus, TextColor> = {
  failed: "status-error-05",
  indeterminate: "text-04",
  passed: "text-05",
  skipped: "text-03",
};

// ---------------------------------------------------------------------------
// ProgressRing — passed and failed shares of the total, as arcs
// ---------------------------------------------------------------------------

interface ProgressRingProps {
  passed: number;
  failed: number;
  total: number;
}

function ProgressRing({ passed, failed, total }: ProgressRingProps) {
  const size = 24;
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
      className="shrink-0 -rotate-90"
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

function CheckRow({ result }: { result: CapabilityCheckResult }) {
  const t = useTranslations("admin.connectorChecks");
  const { icon: StatusIcon, className: iconClassName } =
    STATUS_ICONS[result.status];
  // A failed required check blocks the capability, so the row stands out.
  const blocking = result.status === "failed" && result.required;
  const detail = result.message || t(DETAIL_FALLBACK_KEYS[result.status]);
  const showGuidance =
    (result.status === "failed" || result.status === "indeterminate") &&
    (result.remediation !== null || result.docs_link !== null);

  const row = (
    <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)_auto] items-center gap-4">
      <div className="flex min-w-0 items-center gap-3">
        <StatusIcon size={20} className={cn("shrink-0", iconClassName)} />
        <Text font="main-ui-action" color="text-04" maxLines={1}>
          {result.display_name}
        </Text>
      </div>

      <div className="flex min-w-0 items-center gap-2">
        <Text
          font="main-ui-body"
          color={DETAIL_COLORS[result.status]}
          maxLines={1}
        >
          {detail}
        </Text>
        {showGuidance && (
          <Tooltip
            side="top"
            tooltip={
              <div className="flex flex-col gap-1">
                {result.remediation !== null && (
                  <Text font="secondary-body" color="inherit">
                    {result.remediation}
                  </Text>
                )}
                {result.docs_link !== null && (
                  <a
                    href={result.docs_link}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="underline"
                  >
                    <Text font="secondary-body" color="inherit">
                      {t("docsLink.label")}
                    </Text>
                  </a>
                )}
              </div>
            }
          >
            <span className="inline-flex shrink-0">
              <SvgInfo size={16} className="stroke-status-warning-05" />
            </span>
          </Tooltip>
        )}
      </div>

      <div className="justify-self-end">
        {result.required &&
          (blocking ? (
            <Tag title={t("required.label")} color="gray" />
          ) : (
            <Text font="main-ui-body" color="text-03">
              {t("required.label")}
            </Text>
          ))}
      </div>
    </div>
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
  status: CapabilityCheckStatus;
  results: CapabilityCheckResult[];
}

function CheckGroup({ status, results }: CheckGroupProps) {
  const t = useTranslations("admin.connectorChecks");
  return (
    <Divider
      title={t(GROUP_LABEL_KEYS[status], { count: results.length })}
      foldable
      defaultOpen
    >
      <div className="flex flex-col">
        {results.map((result) => (
          <CheckRow key={result.check_id} result={result} />
        ))}
      </div>
    </Divider>
  );
}

// ---------------------------------------------------------------------------
// ConnectorsCheckCard
// ---------------------------------------------------------------------------

/**
 * The capability-check report for one credential and connector, grouped by
 * outcome like a pull request's checks panel. The backend stores the last
 * completed run and a running flag, so a re-run shows the previous results
 * under a spinner until the new report lands.
 */
export function ConnectorsCheckCard({
  snapshot,
  loading = false,
  running = false,
  onRerun,
}: ConnectorsCheckCardProps) {
  const t = useTranslations("admin.connectorChecks");
  const [collapsed, setCollapsed] = useState(false);

  const results = useMemo(
    () => snapshot?.report?.check_results ?? [],
    [snapshot]
  );
  const groups = useMemo(
    () =>
      GROUP_ORDER.map((status) => ({
        status,
        results: results.filter((result) => result.status === status),
      })).filter((group) => group.results.length > 0),
    [results]
  );
  const passed = results.filter((result) => result.status === "passed").length;
  const failed = results.filter((result) => result.status === "failed").length;
  const isRunning = running || snapshot?.run_status === "running";
  const hasReport = results.length > 0;

  return (
    <Card border="solid" rounding={4} padding={2}>
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-3">
          {isRunning ? (
            <IconLoader size={24} color="text-03" />
          ) : (
            <ProgressRing
              passed={passed}
              failed={failed}
              total={results.length}
            />
          )}
          <div className="flex min-w-0 flex-1 items-baseline gap-2">
            <Text font="heading-h3" color="text-05">
              {t("title")}
            </Text>
            {hasReport && (
              <Text font="heading-h3-muted" color="text-03">
                {t("count", { passed, total: results.length })}
              </Text>
            )}
          </div>
          <div className="flex items-center">
            {onRerun && (
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
              icon={SvgFold}
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
          (loading ? (
            <div className="flex justify-center p-4">
              <IconLoader />
            </div>
          ) : hasReport ? (
            <div className="flex flex-col gap-2">
              {groups.map((group) => (
                <CheckGroup
                  key={group.status}
                  status={group.status}
                  results={group.results}
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
