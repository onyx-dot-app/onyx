"use client";

import type { CredentialRef } from "@/lib/credentials/types";
import { CHECKS_CARD_ID } from "@/lib/connectors/checks/constants";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { TextColor, TextFont } from "@onyx-ai/shared/contracts";
import { ContentAction, Section } from "@opal/layouts";
import { useFormatter, useTranslations } from "next-intl";
import {
  Button,
  Card,
  Divider,
  Fold,
  IconTooltip,
  Log,
  type LogVariant,
  OverflowText,
  SelectCard,
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
  SvgPlay,
  SvgXCircle,
  SvgXOctagon,
  SvgRefreshCw,
} from "@opal/icons";
import type { IconFunctionComponent, IconProps, RichStr } from "@opal/types";
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
  useResetChecksOnCredentialChange,
  useConnectorChecksProgress,
} from "@/lib/connectors/checks/hooks";
import { useSettings } from "@/lib/settings/hooks";

// ---------------------------------------------------------------------------
// Check lines
// ---------------------------------------------------------------------------

type CheckLineState = Exclude<DraftCheckStateKind, "not_applicable">;

/** One check as a line of the card, finished or not. */
export type CheckLine = Pick<
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
// in the primary text colour; the rest stay muted. Only a required failure is
// red and heavy, in `CheckLog`.
const OUTCOME = { font: "main-ui-body", color: "text-04" } as const;
const MUTED = { font: "secondary-body", color: "text-03" } as const;

const INCOMPLETE_LOG = {
  variant: "warning-light",
  icon: SvgAlertCircle,
  detail: "status.indeterminate",
  ...OUTCOME,
  font: "main-ui-action",
  color: "status-warning-05",
} as const;

const CHECK_LOGS = {
  passed: {
    variant: "success-light",
    icon: SvgCheckCircle,
    detail: "status.passed",
    ...OUTCOME,
  },
  failed: {
    variant: "error-light",
    icon: SvgXOctagon,
    detail: "status.failed",
    ...OUTCOME,
  },
  incomplete: INCOMPLETE_LOG,
  // Legacy: an incomplete check in an older stored result.
  indeterminate: INCOMPLETE_LOG,
  skipped: {
    variant: "default",
    icon: SvgXCircle,
    detail: "status.skipped",
    ...MUTED,
  },
  running: {
    variant: "info-light",
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
  { label: "groups.indeterminate", states: ["incomplete", "indeterminate"] },
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
    (check.state === "failed" ||
      check.state === "incomplete" ||
      check.state === "indeterminate") &&
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
  const messageFont: TextFont = blocking ? "main-ui-action" : font;
  const messageColor: TextColor = blocking ? "status-error-05" : color;

  return (
    <Log
      variant={logVariant}
      icon={icon}
      title={check.display_name}
      centerChildren={
        <OverflowText
          as="p"
          font={messageFont}
          color={messageColor}
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
          {check.required && (
            <Tag
              title={t("required.label")}
              color="white"
              variant="status"
              font="secondary-action"
            />
          )}
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
      <Section justifyContent="start" alignItems="stretch" height="fit" gap={1}>
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

export interface CheckLineGroupsProps {
  lines: CheckLine[];
}
/** The lines grouped by outcome, blocking failures first. Empty groups are left out. */
export function CheckLineGroups({ lines }: CheckLineGroupsProps) {
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
  return (
    <Section justifyContent="start" alignItems="stretch" height="fit" gap={0}>
      {groups.map((group) => (
        <CheckGroup
          key={group.label}
          label={group.label}
          checks={group.checks}
        />
      ))}
    </Section>
  );
}

/**
 * The results card, grouped by outcome like a pull request's checks panel.
 * The ring and the title count every check, so a run fills them in as checks
 * finish.
 */
/**
 * A red stop sign, for a run that broke. Content colors its icon from its own
 * stylesheet, so the red is an inline style; Content's sizing stays.
 */
function FailedToRunIcon({ style, ...props }: IconProps) {
  return (
    <SvgXOctagon
      {...props}
      style={{ ...style, color: "var(--status-error-05)" }}
    />
  );
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
  /** Starts folded, showing only the summary line. */
  defaultCollapsed?: boolean;
  /** The run's checks, counted per state. */
  stateCounts: Record<DraftCheckStateKind, number>;
  /** Starts the draft run again after it failed to run. A stored report has no rerun here. */
  onRerun?: () => void;
  /** Each increment opens the card and scrolls it into view. */
  expandRequest?: number;
}
export function CheckCardView({
  status,
  results,
  openChecks,
  inProgressCount,
  expectedCount,
  stateCounts,
  onRerun,
  defaultCollapsed = false,
  expandRequest = 0,
}: CheckCardViewProps) {
  const t = useTranslations("admin.connectorChecks");
  // The same "Re-run Checks" label the saved account cards use.
  const tAccount = useTranslations("admin.connectorsList.add.account");
  const format = useFormatter();
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const cardRef = useRef<HTMLDivElement>(null);
  // The card can outgrow the viewport. Centered, its failed rows still show.
  useEffect(() => {
    if (expandRequest === 0) return;
    setCollapsed(false);
    cardRef.current?.scrollIntoView({ block: "center" });
  }, [expandRequest]);

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
  // Failed required checks block the form or Create.
  const requiredFailed: number = lines.filter(
    (line) => line.state === "failed" && line.required
  ).length;
  const count = useCallback(
    (status: CapabilityCheckStatus): number =>
      results.filter((result) => result.status === status).length,
    [results]
  );
  const incompleteCount: number = count("incomplete") + count("indeterminate");
  const isRunning: boolean = status === "running";
  // A broken run outranks the counts.
  const notice: string | undefined =
    status === "failedToRun" ? t("failedToRun") : undefined;
  const hasResults: boolean = results.length > 0;
  // A run that broke can still list checks: some finished first, or an
  // earlier run's results stay after a failed re-run.
  const hasRows: boolean = hasResults || openChecks.length > 0;
  const total: number = results.length + inProgressCount + expectedCount;
  const hasChecks: boolean = total > 0;

  // What the fold hides, as one comma-separated line in a fixed order, e.g.
  // "2 failed, 1 skipped, 5 successful". Zero counts are left out.
  const summary = useMemo(() => {
    if (notice) return notice;
    if (!hasChecks) return isRunning ? t("state.inProgress") : t("empty.label");
    const parts: Array<[string, number]> = [
      [t("summary.failed", { count: count("failed") }), count("failed")],
      [t("summary.unverified", { count: incompleteCount }), incompleteCount],
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

  const header = (
    <ContentAction
      // A run that broke has no counts, so the ring would read as complete;
      // a red X stands in, without dimming the title.
      icon={notice ? FailedToRunIcon : progress.icon}
      title={t("title")}
      suffix={progress.suffix}
      description={summary}
      sizePreset="main-content"
      variant="section"
      padding={1.5}
      rightChildren={
        <Section flexDirection="row" width="fit" height="fit" gap={0}>
          {(notice !== undefined || stateCounts.failed > 0) &&
            onRerun !== undefined && (
              // A run that broke or failed a check can be tried again without editing settings.
              <Button
                rightIcon={SvgRefreshCw}
                prominence="tertiary"
                disabled={isRunning}
                onClick={onRerun}
              >
                {tAccount("rerunButton.label")}
              </Button>
            )}
          {collapsed && requiredFailed > 0 && (
            <Tag
              icon={SvgXOctagon}
              title={t("requiredFailed", { count: requiredFailed })}
              color="red"
            />
          )}
          {/* Shown unless a run that broke left no rows to fold. */}
          {(!notice || hasRows) && (
            <Button
              icon={collapsed ? SvgExpand : SvgFold}
              prominence="tertiary"
              tooltip={
                collapsed ? t("foldButton.expand") : t("foldButton.fold")
              }
              aria-label={
                collapsed ? t("foldButton.expand") : t("foldButton.fold")
              }
              aria-expanded={!collapsed}
              // Folded, it repeats the card's own action.
              tabIndex={collapsed ? -1 : undefined}
              onClick={() => setCollapsed((value) => !value)}
            />
          )}
        </Section>
      }
    />
  );

  // One card in both states, so folding animates instead of swapping
  // elements. Folded, the whole card is a target that opens it; open, it is
  // passive: no hover, and only its buttons act.
  return (
    <SelectCard
      // Filled rests on white.
      state="filled"
      border="solid"
      rounding={4}
      padding={2}
      passive={!collapsed}
      onClick={collapsed ? () => setCollapsed(false) : undefined}
      ref={cardRef}
      data-testid={CHECKS_CARD_ID}
    >
      <Section justifyContent="start" alignItems="stretch" height="fit" gap={0}>
        {header}
        {/* The header shows the failure; this announces it. */}
        {notice && (
          <span role="alert" className="sr-only">
            {notice}
          </span>
        )}

        <Fold open={!collapsed}>
          {/* The space below the header lives inside the fold, so a closed
              fold takes none. */}
          <Section
            justifyContent="start"
            alignItems="stretch"
            height="fit"
            gap={1}
          >
            {hasRows ? (
              <CheckLineGroups lines={lines} />
            ) : (
              !notice && (
                <Text font="main-ui-body" color="text-03">
                  {isRunning ? t("state.inProgress") : t("empty.label")}
                </Text>
              )
            )}
          </Section>
        </Fold>
      </Section>
    </SelectCard>
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
  /** The saved credential or draft the checks run with; `null` until one is usable. */
  credential: CredentialRef | null;
  /** Locks the Start Checks prompt until the credential section is valid. */
  locked: boolean;
  /** Called when Start Checks starts the first run. */
  onStart?: () => void;
  /** Set when the form edits this pair: the checks are dry runs of it. */
  ccPairId?: number | null;
  /** Each increment opens the results card and scrolls it into view. */
  expandRequest?: number;
}
export default function CredentialChecksCard({
  source,
  credential,
  locked,
  onStart,
  ccPairId = null,
  expandRequest = 0,
}: CredentialChecksCardProps) {
  const promptT = useTranslations("admin.connectorChecks.prompt");
  const { appName } = useSettings();
  useResetChecksOnCredentialChange({ source, credential });
  const checks = useConnectorChecks({ source, credential, ccPairId });
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
            <Button
              icon={SvgPlay}
              disabled={locked}
              onClick={() => {
                checks.begin();
                onStart?.();
              }}
            >
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
      expandRequest={expandRequest}
    />
  );
}
