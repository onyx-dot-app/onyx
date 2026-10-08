"use client";

import { useCallback, useMemo, useState } from "react";
import type { TextColor, TextFont } from "@onyx-ai/shared/contracts";
import { ContentAction, Section } from "@opal/layouts";
import { useFormatter, useTranslations } from "next-intl";
import {
  Button,
  Card,
  Divider,
  IconTooltip,
  Log,
  type LogVariant,
  OverflowText,
  Tag,
  Text,
} from "@opal/components";
import {
  SvgAlertCircle,
  SvgCheckCircle,
  SvgClock,
  SvgExpand,
  SvgFold,
  SvgHourglass,
  SvgMinusCircle,
  SvgPlay,
  SvgRefreshCw,
  SvgXCircle,
} from "@opal/icons";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { escapeMarkdown, markdown } from "@opal/utils";
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

// ---------------------------------------------------------------------------
// Check lines
// ---------------------------------------------------------------------------

type CheckLineState = Exclude<DraftCheckStateKind, "not_applicable">;

/** One check as a line of the card, finished or not. */
type CheckLine = Pick<
  DraftCheckState,
  | "capability"
  | "check_id"
  | "display_name"
  | "required"
  | "message"
  | "remediation"
  | "docs_link"
> & { state: CheckLineState };

// Outcomes that need reading (passed, failed, unverified) show their details
// in a heavier font and their status colour; the rest stay muted.
const OUTCOME_FONT: TextFont = "main-ui-action";
const MUTED = { font: "secondary-body", color: "text-03" } as const;

const CHECK_LOGS = {
  passed: {
    variant: "success-light",
    icon: SvgCheckCircle,
    detail: "status.passed",
    font: OUTCOME_FONT,
    color: "text-04",
  },
  // A failed required check blocks, so `CheckLog` makes it heavy.
  failed: {
    variant: "error-light",
    icon: SvgXCircle,
    detail: "status.failed",
    font: OUTCOME_FONT,
    color: "status-error-05",
  },
  indeterminate: {
    variant: "warning-light",
    icon: SvgAlertCircle,
    detail: "status.indeterminate",
    font: OUTCOME_FONT,
    color: "theme-amber-05",
  },
  skipped: {
    variant: "default",
    icon: SvgMinusCircle,
    detail: "status.skipped",
    ...MUTED,
  },
  running: {
    variant: "default",
    icon: IconLoader,
    detail: "status.running",
    ...MUTED,
  },
  pending: {
    variant: "default",
    icon: SvgClock,
    detail: "status.pending",
    ...MUTED,
  },
  waiting: {
    variant: "default",
    icon: SvgHourglass,
    detail: "status.waiting",
    ...MUTED,
  },
} as const satisfies Record<
  CheckLineState,
  {
    variant: LogVariant;
    icon: IconFunctionComponent;
    detail: string;
    font: TextFont;
    color: TextColor;
  }
>;

/** Group order: what blocks first, what is unknown next, then the rest. */
const GROUPS = [
  { label: "groups.failed", states: ["failed"] },
  { label: "groups.indeterminate", states: ["indeterminate"] },
  { label: "groups.passed", states: ["passed"] },
  { label: "groups.skipped", states: ["skipped"] },
  { label: "groups.running", states: ["running"] },
  { label: "groups.expected", states: ["pending", "waiting"] },
] as const satisfies ReadonlyArray<{
  label: string;
  states: readonly CheckLineState[];
}>;

interface CheckLogProps {
  check: CheckLine;
}
function CheckLog({ check }: CheckLogProps) {
  const t = useTranslations("admin.connectorChecks");
  const { variant, icon, detail, font, color } = CHECK_LOGS[check.state];
  // A failed required check blocks the form or Create, so its line is heavy.
  const blocking = check.state === "failed" && check.required;
  // How to fix a failed or unverified check, with a link to the docs.
  const guidance: RichStr | undefined =
    (check.state === "failed" || check.state === "indeterminate") &&
    (check.remediation !== null || check.docs_link !== null)
      ? markdown(
          ...(check.remediation !== null
            ? [escapeMarkdown(check.remediation)]
            : []),
          ...(check.docs_link !== null
            ? [`[${escapeMarkdown(t("docsLink.label"))}](${check.docs_link})`]
            : [])
        )
      : undefined;

  const logVariant: LogVariant = blocking ? "error-heavy" : variant;

  return (
    <Log
      variant={logVariant}
      icon={icon}
      title={check.display_name}
      centerChildren={
        <OverflowText
          as="p"
          font={font}
          color={color}
          textPosition="text-start"
        >
          {check.message || t(detail)}
        </OverflowText>
      }
      rightChildren={
        <Section flexDirection="row" width="fit" height="fit" gap={1}>
          {guidance !== undefined && (
            <IconTooltip
              status={check.state === "failed" ? "error" : "warning"}
              tooltip={guidance}
            />
          )}
          {check.required && <Tag title={t("required.label")} color="gray" />}
        </Section>
      }
    />
  );
}

interface CheckGroupProps {
  label: (typeof GROUPS)[number]["label"];
  checks: CheckLine[];
}
function CheckGroup({ label, checks }: CheckGroupProps) {
  const t = useTranslations("admin.connectorChecks");
  return (
    <Divider title={t(label, { count: checks.length })} foldable defaultOpen>
      <Section justifyContent="start" alignItems="stretch" height="fit" gap={0}>
        {checks.map((check) => (
          // The backend repeats some checks across capabilities under the
          // same ID, so the capability keeps the key unique.
          <CheckLog
            key={`${check.capability}:${check.check_id}`}
            check={check}
          />
        ))}
      </Section>
    </Divider>
  );
}

/**
 * The results card, grouped by outcome like a pull request's checks panel.
 * The ring and the title count every check, so a run fills them in as checks
 * finish.
 */
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

  const lines: CheckLine[] = useMemo(
    () => [
      ...results.map((result) => ({ ...result, state: result.status })),
      ...openChecks.flatMap((check) =>
        check.state === "not_applicable"
          ? []
          : [{ ...check, state: check.state }]
      ),
    ],
    [results, openChecks]
  );
  const groups = useMemo(
    () =>
      GROUPS.map((group) => ({
        label: group.label,
        checks: lines.filter((line) =>
          (group.states as readonly CheckLineState[]).includes(line.state)
        ),
      })).filter((group) => group.checks.length > 0),
    [lines]
  );
  // Failed required checks block the form or Create.
  const requiredFailed: number = lines.filter(
    (line) => line.state === "failed" && line.required
  ).length;
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
      <Section justifyContent="start" alignItems="stretch" height="fit" gap={1}>
        <ContentAction
          icon={progress.icon}
          title={t("title")}
          suffix={progress.suffix}
          description={collapsed ? summary : undefined}
          sizePreset="main-content"
          variant="section"
          padding={1.5}
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
              {!collapsed && requiredFailed > 0 && (
                <Tag
                  title={t("requiredFailed", { count: requiredFailed })}
                  color="red"
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
              gap={0}
            >
              {groups.map((group) => (
                <CheckGroup
                  key={group.label}
                  label={group.label}
                  checks={group.checks}
                />
              ))}
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

// ---------------------------------------------------------------------------
// CredentialChecksCard
// ---------------------------------------------------------------------------

/**
 * The capability checks for the connector being set up. Reads the shared
 * check session itself: before a run it shows the Start Checks prompt, after
 * one the results card. The checks run only on request, so a page visit costs
 * no credential calls.
 */
export interface CredentialChecksCardProps {
  source: ConfigurableSources;
  /** The credential the checks run with; `null` until one is usable. */
  credentialId: number | null;
  /** Locks the Start Checks prompt until the credential section is valid. */
  locked: boolean;
}
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
