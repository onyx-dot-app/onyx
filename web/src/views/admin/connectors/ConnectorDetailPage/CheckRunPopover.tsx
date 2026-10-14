"use client";

import { useFormatter, useTranslations } from "next-intl";
import { Button, Popover, ShadowDiv, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgCheckSquare, SvgX } from "@opal/icons";
import type { CapabilityCheckStatus } from "@/lib/connectors/checks/types";
import type { CheckRunSnapshot } from "@/lib/connectors/types";
import { CheckLineGroups } from "@/views/admin/connectors/AddConnectorPage/components/CredentialChecksCard";
import { checkCount } from "@/views/admin/connectors/ConnectorDetailPage/RunRow";

/** Opens the results of one check run. Place it inside the Popover that holds the content. */
export function CheckRunTrigger() {
  const t = useTranslations("admin.connector.runs");
  return (
    <Popover.Trigger asChild>
      <Button
        icon={SvgCheckSquare}
        prominence="tertiary"
        size="xs"
        tooltip={t("actions.checks")}
        aria-label={t("actions.checks")}
      />
    </Popover.Trigger>
  );
}

export interface CheckRunPopoverContentProps {
  run: CheckRunSnapshot;
  /** Opens beside a small trigger, such as an activity card's tag, instead of under a row-wide anchor. */
  beside?: boolean;
}

/** The checks of one run grouped by outcome. Under a row it is as wide as the caller's Popover.Anchor. */
export default function CheckRunPopoverContent({
  run,
  beside = false,
}: CheckRunPopoverContentProps) {
  const t = useTranslations("admin.connector.runs.checkResults");
  const tChecks = useTranslations("admin.connectorChecks");
  const format = useFormatter();
  // Zero counts are left out, as the checks card does.
  const parts = [
    { status: "failed", label: "summary.failed" },
    { status: "indeterminate", label: "summary.unverified" },
    { status: "skipped", label: "summary.skipped" },
    { status: "passed", label: "summary.successful" },
  ] as const satisfies ReadonlyArray<{
    status: CapabilityCheckStatus;
    label: string;
  }>;
  const labels: string[] = parts
    .filter((part) => checkCount(run, part.status) > 0)
    .map((part) =>
      tChecks(part.label, { count: checkCount(run, part.status) })
    );
  const summary = format.list(labels, { type: "unit" });

  return (
    <Popover.Content
      width={beside ? "3xl" : "trigger"}
      side={beside ? "left" : undefined}
      align="start"
      sideOffset={beside ? undefined : -8}
      aria-label={t("title")}
    >
      <Section
        alignItems="stretch"
        gap={0}
        padding={1}
        height="auto"
        className="min-h-0"
      >
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
            <Text font="secondary-action" color="text-04">
              {t("title", { count: run.check_results.length })}
            </Text>
            <Text font="secondary-body" color="text-03">
              {summary}
            </Text>
          </Section>
          <Popover.Close asChild>
            <Button
              icon={SvgX}
              prominence="tertiary"
              size="xs"
              aria-label={t("close")}
            />
          </Popover.Close>
        </Section>
        <ShadowDiv>
          <CheckLineGroups
            lines={run.check_results.map((result) => ({
              ...result,
              state: result.status,
            }))}
          />
        </ShadowDiv>
      </Section>
    </Popover.Content>
  );
}
