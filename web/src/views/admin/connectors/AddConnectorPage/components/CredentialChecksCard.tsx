"use client";

import { useCallback, useMemo, useState } from "react";
import { ContentAction, Section } from "@opal/layouts";
import { useFormatter, useTranslations } from "next-intl";
import { Button, Card, Divider, Tag, Text, Tooltip } from "@opal/components";
import {
  SvgAlertCircle,
  SvgCheckCircle,
  SvgExpand,
  SvgFold,
  SvgInfo,
  SvgMinusCircle,
  SvgRefreshCw,
  SvgXCircle,
  SvgProgressRing,
} from "@opal/icons";
import type { IconFunctionComponent, IconProps } from "@opal/types";
import type { TextColor } from "@onyx-ai/shared/contracts";
import { cn } from "@opal/utils";
import type {
  CapabilityCheckResult,
  CapabilityCheckStatus,
  ConnectorChecksStatus,
  DraftCheckStateKind,
} from "@/lib/connectors/checks/types";
import type { ConfigurableSources } from "@/lib/connectors/types/source";
import {
  useConnectorChecks,
  useConnectorChecksProgress,
} from "@/lib/connectors/checks/hooks";
import ConnectorsCheckPromptCard from "@/views/admin/connectors/AddConnectorPage/components/ConnectorsCheckPromptCard";

export interface CredentialChecksCardProps {
  source: ConfigurableSources;
  /** The credential the checks run with; `null` until one is usable. */
  credentialId: number | null;
  /** Locks the Start Checks prompt until the credential section is valid. */
  locked: boolean;
}

interface CheckCardViewProps {
  status: ConnectorChecksStatus;
  /** The finished checks, in any order. */
  results: CapabilityCheckResult[];
  /** Checks queued or running now. */
  inProgressCount: number;
  /** Checks waiting on a form field before they can run. */
  expectedCount: number;
  /** The run's checks, counted per state. */
  stateCounts: Record<DraftCheckStateKind, number>;
  onRerun: () => void;
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
          // The backend repeats some checks across capabilities under the
          // same ID, so the capability keeps the key unique.
          <CheckRow
            key={`${result.capability}:${result.check_id}`}
            result={result}
          />
        ))}
      </div>
    </Divider>
  );
}

// ---------------------------------------------------------------------------
// CredentialChecksCard
// ---------------------------------------------------------------------------

/**
 * The capability checks for the connector being set up. Reads the shared
 * check session itself: before a run it shows the Start Checks prompt, after
 * one the results card.
 */
export default function CredentialChecksCard({
  source,
  credentialId,
  locked,
}: CredentialChecksCardProps) {
  const checks = useConnectorChecks({ source, credentialId });
  if (checks.status === "notStarted") {
    return (
      <ConnectorsCheckPromptCard disabled={locked} onStart={checks.begin} />
    );
  }
  return (
    <CheckCardView
      status={checks.status}
      results={checks.results}
      inProgressCount={checks.inProgressCount}
      expectedCount={checks.expectedCount}
      stateCounts={checks.stateCounts}
      onRerun={checks.rerun}
    />
  );
}

/**
 * The results card, grouped by outcome like a pull request's checks panel.
 * The ring and the title count every check, so a run fills them in as checks
 * finish.
 */
function CheckCardView({
  status,
  results,
  inProgressCount,
  expectedCount,
  stateCounts,
  onRerun,
}: CheckCardViewProps) {
  const t = useTranslations("admin.connectorChecks");
  const format = useFormatter();
  const [collapsed, setCollapsed] = useState(false);

  const groups = useMemo(
    () =>
      GROUP_ORDER.map((status) => ({
        status,
        results: results.filter((result) => result.status === status),
      })).filter((group) => group.results.length > 0),
    [results]
  );
  const count = useCallback(
    (status: CapabilityCheckStatus): number =>
      results.filter((result) => result.status === status).length,
    [results]
  );
  const isRunning: boolean = status === "running";
  // A broken run or a changed configuration outranks the counts.
  const notice: string | undefined =
    status === "failedToRun"
      ? t("failedToRun")
      : status === "stale"
        ? t("stale")
        : undefined;
  const hasResults: boolean = results.length > 0;
  const total: number = results.length + inProgressCount + expectedCount;
  const hasChecks: boolean = total > 0;

  // What the fold hides, as one comma-separated line in a fixed order, e.g.
  // "2 failed, 1 skipped, 5 successful". Zero counts are left out.
  const summary = useMemo(() => {
    if (notice) return notice;
    if (!hasChecks) return isRunning ? t("running.label") : t("empty.label");
    const parts: Array<[string, number]> = [
      [t("summary.failed", { count: count("failed") }), count("failed")],
      [
        t("summary.unverified", { count: count("indeterminate") }),
        count("indeterminate"),
      ],
      [t("summary.inProgress", { count: inProgressCount }), inProgressCount],
      [t("summary.expected", { count: expectedCount }), expectedCount],
      [t("summary.skipped", { count: count("skipped") }), count("skipped")],
      [t("summary.successful", { count: count("passed") }), count("passed")],
    ];
    return format.list(
      parts.filter(([, n]) => n > 0).map(([label]) => label),
      { type: "unit" }
    );
  }, [
    notice,
    hasChecks,
    isRunning,
    count,
    inProgressCount,
    expectedCount,
    t,
    format,
  ]);

  const progress = useConnectorChecksProgress(stateCounts, status);

  return (
    <Card border="solid" rounding={4} padding={2}>
      <div className="flex flex-col gap-3">
        <ContentAction
          icon={progress.icon}
          title={t("title")}
          suffix={progress.suffix}
          description={collapsed ? summary : undefined}
          sizePreset="main-content"
          variant="section"
          padding={1}
          rightChildren={
            <Section flexDirection="row" width="fit" height="fit" gap={0}>
              {!collapsed && (
                <Button
                  icon={SvgRefreshCw}
                  prominence="internal"
                  tooltip={t("rerunButton.label")}
                  aria-label={t("rerunButton.label")}
                  disabled={isRunning}
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
            </Section>
          }
        />

        {!collapsed && notice && (
          <Text
            font="main-ui-body"
            color={status === "failedToRun" ? "status-error-05" : "text-04"}
            role={status === "failedToRun" ? "alert" : "status"}
          >
            {notice}
          </Text>
        )}

        {!collapsed &&
          (hasResults ? (
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
            !notice && (
              <Text font="main-ui-body" color="text-03">
                {isRunning ? t("running.label") : t("empty.label")}
              </Text>
            )
          ))}
      </div>
    </Card>
  );
}
