"use client";

import { useFormatter, useTranslations } from "next-intl";
import {
  Button,
  Popover,
  SelectButton,
  ShadowDiv,
  Text,
} from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgListCheck, SvgX } from "@opal/icons";
import type { CapabilityCheckStatus } from "@/lib/connectors/checks/types";
import type { CheckRunSnapshot } from "@/lib/connectors/types";
import {
  NO_CHECKS,
  useConnectorChecksProgress,
} from "@/lib/connectors/checks/hooks";
import { CheckLineGroups } from "@/views/admin/connectors/AddConnectorPage/components/CredentialChecksCard";
import { checkCount } from "@/views/admin/connectors/ConnectorDetailPage/RunRow";
import {
  PLACEMENT_PROPS,
  type PopoverPlacement,
} from "@/views/admin/connectors/ConnectorDetailPage/popoverPlacement";

/** Opens the results of one check run. Place it inside the Popover that holds the content. */
export interface CheckRunTriggerProps {
  /** Whether its popover is open. The open trigger shows selected. */
  open?: boolean;
}
export function CheckRunTrigger({ open = false }: CheckRunTriggerProps) {
  const t = useTranslations("admin.connector.runs");
  return (
    <Popover.Trigger asChild>
      <SelectButton
        icon={SvgListCheck}
        variant="select-light"
        state={open ? "selected" : "empty"}
        size="xs"
        tooltip={t("actions.checks")}
        aria-label={t("actions.checks")}
      />
    </Popover.Trigger>
  );
}

export interface CheckRunPopoverContentProps {
  run: CheckRunSnapshot;
  /** Opens beside or below a card from a small trigger, such as an activity card's tag; unset, under a row-wide anchor. */
  placement?: PopoverPlacement;
}

/** The checks of one run grouped by outcome. Under a row it is as wide as the caller's Popover.Anchor. */
export default function CheckRunPopoverContent({
  run,
  placement,
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
  const stateCounts = { ...NO_CHECKS };
  for (const result of run.check_results) stateCounts[result.status] += 1;
  // The checks card's ring, for a stored run.
  const { icon: Ring } = useConnectorChecksProgress(stateCounts, "passed");

  return (
    <Popover.Content
      width={placement === undefined ? "trigger" : "3xl"}
      {...(placement === undefined
        ? { align: "start", sideOffset: -8 }
        : PLACEMENT_PROPS[placement])}
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
            <Section
              flexDirection="row"
              justifyContent="start"
              alignItems="center"
              gap={1}
              height="fit"
            >
              <Ring size={16} className="shrink-0" />
              <Text font="main-ui-action" color="text-04">
                {t("title")}
              </Text>
              <Text font="main-ui-muted" color="text-03">
                {t("count", { count: run.check_results.length })}
              </Text>
            </Section>
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
