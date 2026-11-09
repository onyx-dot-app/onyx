"use client";

import { useFormatter, useTranslations } from "next-intl";
import { Popover, ShadowDiv, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import type { CheckRunSnapshot, CheckRunStatus } from "@/lib/connectors/types";
import type {
  CapabilityCheckResult,
  ConnectorChecksStatus,
} from "@/lib/connectors/checks/types";
import {
  NO_CHECKS,
  useConnectorChecksProgress,
} from "@/lib/connectors/checks/hooks";
import { CheckLineGroups } from "@/views/admin/connectors/AddConnectorPage/components/CredentialChecksCard";
import {
  checkCount,
  shownCheckResults,
} from "@/views/admin/connectors/ConnectorDetailPage/RunRow";
import {
  DetailsCloseButton,
  InlineDetailsCard,
} from "@/views/admin/connectors/ConnectorDetailPage/InlineDetails";
import {
  PLACEMENT_PROPS,
  type PopoverPlacement,
} from "@/views/admin/connectors/ConnectorDetailPage/popoverPlacement";

const RUN_STATUS: Record<CheckRunStatus, ConnectorChecksStatus> = {
  running: "running",
  passed: "passed",
  failed: "failed",
  failed_to_run: "failedToRun",
};

interface CheckRunDetailsProps {
  run: CheckRunSnapshot;
  /** Closes an inline card. Unset, the close button closes the enclosing Popover. */
  onClose?: () => void;
}

/** The checks of one run grouped by outcome, under a header with their summary. */
function CheckRunDetails({ run, onClose }: CheckRunDetailsProps) {
  const t = useTranslations("admin.connector.runs.checkResults");
  const tChecks = useTranslations("admin.connectorChecks");
  const format = useFormatter();
  const results: CapabilityCheckResult[] = shownCheckResults(run);
  // Zero counts are left out, in the groups' order, as the checks card does.
  const parts = [
    { label: "summary.failed", count: checkCount(run, "failed") },
    {
      label: "summary.unverified",
      count: checkCount(run, "incomplete") + checkCount(run, "indeterminate"),
    },
    { label: "summary.successful", count: checkCount(run, "passed") },
    { label: "summary.skipped", count: checkCount(run, "skipped") },
  ] as const;
  const labels: string[] = parts
    .filter((part) => part.count > 0)
    .map((part) => tChecks(part.label, { count: part.count }));
  const summary = format.list(labels, { type: "unit" });
  const stateCounts = { ...NO_CHECKS };
  for (const result of results) stateCounts[result.status] += 1;
  // The checks card's header icon, for a stored run.
  const { icon: Ring } = useConnectorChecksProgress(
    stateCounts,
    RUN_STATUS[run.status],
    results.some((result) => result.status === "failed" && result.required)
  );
  return (
    <Section alignItems="stretch" gap={0} height="auto" className="min-h-0">
      <Section
        flexDirection="row"
        justifyContent="between"
        alignItems="start"
        gap={1}
        height="fit"
        className="shrink-0"
      >
        <Section
          alignItems="start"
          gap={0}
          padding={1}
          height="fit"
          className="min-w-0 flex-1"
        >
          <Section
            flexDirection="row"
            justifyContent="start"
            gap={1}
            height="fit"
          >
            <Ring size={16} className="shrink-0" />
            <Text font="main-ui-action" color="text-04">
              {t("title")}
            </Text>
            <Text font="main-ui-muted" color="text-03">
              {t("count", { count: results.length })}
            </Text>
          </Section>
          <Text font="secondary-body" color="text-03">
            {summary}
          </Text>
        </Section>
        <DetailsCloseButton label={t("close")} onClose={onClose} />
      </Section>
      <ShadowDiv>
        {/* The inline card lists outcomes only, so its rows do not fold open. */}
        <CheckLineGroups
          lines={results.map((result) => ({
            ...result,
            state: result.status,
          }))}
          withDetails={onClose === undefined}
        />
      </ShadowDiv>
    </Section>
  );
}

export interface CheckRunPopoverContentProps {
  run: CheckRunSnapshot;
  /** Where it opens beside or below a card from a small trigger, such as an activity card's tag. */
  placement: PopoverPlacement;
}

/** A check run's results in a popover beside or below a card. */
export default function CheckRunPopoverContent({
  run,
  placement,
}: CheckRunPopoverContentProps) {
  const t = useTranslations("admin.connector.runs.checkResults");
  return (
    <Popover.Content
      width={160}
      {...PLACEMENT_PROPS[placement]}
      aria-label={t("title")}
    >
      <Section
        alignItems="stretch"
        padding={1}
        height="auto"
        className="min-h-0"
      >
        <CheckRunDetails run={run} />
      </Section>
    </Popover.Content>
  );
}

export interface CheckRunCardProps {
  run: CheckRunSnapshot;
  onClose: () => void;
}

/** A check run's results in a card directly under its run line. */
export function CheckRunCard({ run, onClose }: CheckRunCardProps) {
  const t = useTranslations("admin.connector.runs.checkResults");
  return (
    <InlineDetailsCard label={t("title")} onClose={onClose}>
      <CheckRunDetails run={run} onClose={onClose} />
    </InlineDetailsCard>
  );
}
