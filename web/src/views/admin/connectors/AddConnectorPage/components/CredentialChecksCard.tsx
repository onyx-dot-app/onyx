"use client";

import { useCallback, useMemo, useState } from "react";
import { ContentAction, Section } from "@opal/layouts";
import { useFormatter, useTranslations } from "next-intl";
import { Button, Card, Divider, Tag, Text, Tooltip } from "@opal/components";
import {
  SvgAlertCircle,
  SvgCheckCircle,
  SvgClock,
  SvgExpand,
  SvgFold,
  SvgHourglass,
  SvgInfo,
  SvgMinusCircle,
  SvgPlay,
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
  DraftCheckState,
  DraftCheckStateKind,
} from "@/lib/connectors/checks/types";
import { IconLoader } from "@opal/loaders";
import type { ConfigurableSources } from "@/lib/connectors/types/source";
import {
  useConnectorChecks,
  useConnectorChecksAutoRun,
  useConnectorChecksProgress,
} from "@/lib/connectors/checks/hooks";
import { useSettings } from "@/lib/settings/hooks";

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
  /** The checks still to finish: running, queued or waiting. */
  openChecks: DraftCheckState[];
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

// A row's name and detail split the width 1 : 1.6; `min-w-0` lets their text
// truncate instead of widening the row.
const NAME_COLUMN = "min-w-0 flex-1";
const DETAIL_COLUMN = "min-w-0 flex-[1.6]";

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
    <Section flexDirection="row" justifyContent="start" height="fit" gap={4}>
      <Section
        flexDirection="row"
        justifyContent="start"
        height="fit"
        gap={3}
        className={NAME_COLUMN}
      >
        <StatusIcon size={20} className={cn("shrink-0", iconClassName)} />
        <Text font="main-ui-action" color="text-04" maxLines={1}>
          {result.display_name}
        </Text>
      </Section>

      <Section
        flexDirection="row"
        justifyContent="start"
        height="fit"
        gap={2}
        className={DETAIL_COLUMN}
      >
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
              <Section
                justifyContent="start"
                alignItems="start"
                width="fit"
                height="fit"
                gap={1}
              >
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
              </Section>
            }
          >
            <Section width="fit" height="fit">
              <SvgInfo size={16} className="stroke-status-warning-05" />
            </Section>
          </Tooltip>
        )}
      </Section>

      <Section width="fit" height="fit">
        {result.required &&
          (blocking ? (
            <Tag title={t("required.label")} color="gray" />
          ) : (
            <Text font="main-ui-body" color="text-03">
              {t("required.label")}
            </Text>
          ))}
      </Section>
    </Section>
  );

  return blocking ? (
    <Card color="status-error-00" rounding={3} padding={2} data-blocking>
      {row}
    </Card>
  ) : (
    <Section height="fit" padding={2}>
      {row}
    </Section>
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
      <Section justifyContent="start" alignItems="stretch" height="fit" gap={0}>
        {results.map((result) => (
          // The backend repeats some checks across capabilities under the
          // same ID, so the capability keeps the key unique.
          <CheckRow
            key={`${result.capability}:${result.check_id}`}
            result={result}
          />
        ))}
      </Section>
    </Divider>
  );
}

// ---------------------------------------------------------------------------
// OpenCheckRow — a check still to finish
// ---------------------------------------------------------------------------

type OpenState = "running" | "pending" | "waiting";

const OPEN_ICONS: Record<OpenState, IconFunctionComponent> = {
  running: IconLoader,
  pending: SvgClock,
  waiting: SvgHourglass,
};

const OPEN_DETAIL_KEYS = {
  running: "status.running",
  pending: "status.pending",
  waiting: "status.waiting",
} as const satisfies Record<OpenState, string>;

function isOpenState(state: DraftCheckState["state"]): state is OpenState {
  return state === "running" || state === "pending" || state === "waiting";
}

function OpenCheckRow({ check }: { check: DraftCheckState }) {
  const t = useTranslations("admin.connectorChecks");
  if (!isOpenState(check.state)) return null;
  const Icon = OPEN_ICONS[check.state];
  // A waiting check says what it waits for when the backend tells it.
  const detail =
    check.state === "waiting" && check.message
      ? check.message
      : t(OPEN_DETAIL_KEYS[check.state]);

  return (
    <Section height="fit" padding={2}>
      <Section flexDirection="row" justifyContent="start" height="fit" gap={4}>
        <Section
          flexDirection="row"
          justifyContent="start"
          height="fit"
          gap={3}
          className={NAME_COLUMN}
        >
          <Icon size={20} className="shrink-0 stroke-text-03" />
          <Text font="main-ui-action" color="text-04" maxLines={1}>
            {check.display_name}
          </Text>
        </Section>
        <Section
          flexDirection="row"
          justifyContent="start"
          height="fit"
          className={DETAIL_COLUMN}
        >
          <Text font="main-ui-body" color="text-03" maxLines={1}>
            {detail}
          </Text>
        </Section>
        <Section width="fit" height="fit">
          {check.required && (
            <Text font="main-ui-body" color="text-03">
              {t("required.label")}
            </Text>
          )}
        </Section>
      </Section>
    </Section>
  );
}

interface OpenCheckGroupProps {
  label: "groups.running" | "groups.expected";
  checks: DraftCheckState[];
}

function OpenCheckGroup({ label, checks }: OpenCheckGroupProps) {
  const t = useTranslations("admin.connectorChecks");
  if (checks.length === 0) return null;
  return (
    <Divider title={t(label, { count: checks.length })} foldable defaultOpen>
      <Section justifyContent="start" alignItems="stretch" height="fit" gap={0}>
        {checks.map((check) => (
          <OpenCheckRow
            key={`${check.capability}:${check.check_id}`}
            check={check}
          />
        ))}
      </Section>
    </Divider>
  );
}

// ---------------------------------------------------------------------------
// CredentialChecksCard
// ---------------------------------------------------------------------------

/**
 * The capability checks for the connector being set up. Reads the shared
 * check session itself: before a run it shows the Start Checks prompt, after
 * one the results card. The checks run only on request, so a page visit costs
 * no credential calls.
 */
export default function CredentialChecksCard({
  source,
  credentialId,
  locked,
}: CredentialChecksCardProps) {
  const promptT = useTranslations("admin.connectorChecks.prompt");
  const { appName } = useSettings();
  const checks = useConnectorChecks({ source, credentialId });
  useConnectorChecksAutoRun(checks);
  // No check applies to this source and access type: nothing to start.
  if (checks.plan?.checks.every((check) => check.state === "not_applicable")) {
    return null;
  }
  if (checks.status === "notStarted") {
    return (
      <Card border="solid" rounding={4} padding={4}>
        <ContentAction
          title={promptT("title")}
          description={promptT("description", { appName })}
          sizePreset="main-content"
          variant="section"
          center
          padding={0}
          rightChildren={
            <Button icon={SvgPlay} disabled={locked} onClick={checks.begin}>
              {promptT("startButton.label")}
            </Button>
          }
        />
      </Card>
    );
  }
  return (
    <CheckCardView
      status={checks.status}
      results={checks.results}
      openChecks={checks.openChecks}
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
  openChecks,
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
  // A broken run outranks the counts.
  const notice: string | undefined =
    status === "failedToRun" ? t("failedToRun") : undefined;
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
      <Section justifyContent="start" alignItems="stretch" height="fit" gap={3}>
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
          <Text font="main-ui-body" color="status-error-05" role="alert">
            {notice}
          </Text>
        )}

        {!collapsed &&
          (hasResults || openChecks.length > 0 ? (
            <Section
              justifyContent="start"
              alignItems="stretch"
              height="fit"
              gap={2}
            >
              {groups.map((group) => (
                <CheckGroup
                  key={group.status}
                  status={group.status}
                  results={group.results}
                />
              ))}
              <OpenCheckGroup
                label="groups.running"
                checks={openChecks.filter((check) => check.state === "running")}
              />
              <OpenCheckGroup
                label="groups.expected"
                checks={openChecks.filter((check) => check.state !== "running")}
              />
            </Section>
          ) : (
            !notice && (
              <Text font="main-ui-body" color="text-03">
                {isRunning ? t("running.label") : t("empty.label")}
              </Text>
            )
          ))}
      </Section>
    </Card>
  );
}
