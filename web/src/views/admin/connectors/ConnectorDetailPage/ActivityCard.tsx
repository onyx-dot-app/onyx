"use client";

import { useFormatter, useTranslations } from "next-intl";
import { Button, Card, Popover, Tag, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import {
  SvgAlertTriangle,
  SvgCheckAll,
  SvgCheckCircle,
  SvgFileText,
  SvgTextLines,
  SvgXCircle,
  SvgXOctagon,
} from "@opal/icons";
import type { CardColor, IconFunctionComponent } from "@opal/types";
import type { CCPairRun } from "@/lib/connectors/types";
import type { ActivityGroup } from "@/lib/connectors/ccPair/hooks";
import CheckRunPopoverContent from "@/views/admin/connectors/ConnectorDetailPage/CheckRunPopover";
import FailedDocsPopoverContent from "@/views/admin/connectors/ConnectorDetailPage/FailedDocsPopover";
import StackTracePopoverContent from "@/views/admin/connectors/ConnectorDetailPage/StackTracePopover";
import {
  RUN_KIND_ICONS,
  RUN_TIME_FORMAT,
  isActive,
  runErrorMessage,
  runMinutes,
  runMoved,
  runTrace,
  runWarnings,
} from "@/views/admin/connectors/ConnectorDetailPage/RunRow";

const GROUP_STYLE: Record<
  ActivityGroup,
  { color: CardColor; icon: IconFunctionComponent; stroke: string }
> = {
  failures: {
    color: "status-error-00",
    icon: SvgXCircle,
    stroke: "stroke-status-error-05",
  },
  errors: {
    color: "status-warning-00",
    icon: SvgAlertTriangle,
    stroke: "stroke-theme-amber-05",
  },
  resolved: {
    color: "background-tint-01",
    icon: SvgCheckCircle,
    stroke: "stroke-status-success-05",
  },
};

/** The title's state key: how the run stands in its group. */
function cardState(
  run: CCPairRun,
  group: ActivityGroup
): "failed" | "running" | "stopped" | "errors" | "resolved" {
  switch (group) {
    case "failures":
      return "failed";
    case "resolved":
      return "resolved";
    case "errors":
      if (isActive(run)) return "running";
      return run.attempt.status === "canceled" ||
        run.attempt.status === "interrupted"
        ? "stopped"
        : "errors";
  }
}

export interface ActivityCardProps {
  ccPairId: number;
  run: CCPairRun;
  group: ActivityGroup;
  /** Whether the viewer may re-fetch single documents of this pair. Hides the resolve actions otherwise. */
  canResolve: boolean;
  /** Resolves these errors of the run, or every open one when `null`. */
  onResolve: (errorIds: number[] | null) => void;
  /** A resolve is in flight, so the resolve actions wait for it. */
  resolving: boolean;
}

/** One failed run, or one run with document errors: when, which kind, how it ended, its trace and failed documents. */
export default function ActivityCard({
  ccPairId,
  run,
  group,
  canResolve,
  onResolve,
  resolving,
}: ActivityCardProps) {
  const t = useTranslations("admin.connector.activity");
  const tRuns = useTranslations("admin.connector.runs");
  const format = useFormatter();
  const active = isActive(run);
  const style = GROUP_STYLE[group];
  const StatusIcon = active ? IconLoader : style.icon;
  const KindIcon = RUN_KIND_ICONS[run.kind];
  const minutes = runMinutes(run);
  const warnings = runWarnings(run);
  const trace = runTrace(run);
  // The list holds open document errors, so only an index attempt with some lists its documents.
  const openDocs =
    run.kind === "indexing" ? run.attempt.open_doc_error_count : 0;
  const listsDocs = openDocs > 0;
  const resolvable = canResolve && listsDocs;
  // A failed check run lists what failed instead of a stack trace.
  const listsChecks = run.kind === "checks" && warnings > 0;

  // A failure explains itself. A run with errors reports what it still did.
  let description: string | null = null;
  if (group === "failures") {
    description =
      runErrorMessage(run) ??
      (listsChecks ? t("description.checksFailed", { count: warnings }) : null);
  } else if (minutes !== null) {
    description = t(`description.${run.kind}`, {
      count: runMoved(run),
      minutes,
    });
  }
  const docsLabel =
    group === "resolved"
      ? t("tags.resolvedDocs", { count: warnings })
      : t(`tags.${run.kind}`, { count: listsDocs ? openDocs : warnings });

  return (
    <Card color={style.color} border="none" rounding={2} padding={1}>
      <Section alignItems="stretch" gap={0} height="fit">
        <Section
          flexDirection="row"
          alignItems="start"
          gap={1}
          padding={1}
          height="fit"
        >
          <Section
            alignItems="center"
            justifyContent="center"
            padding={0.5}
            width="fit"
            height="fit"
          >
            <StatusIcon size={16} className={style.stroke} />
          </Section>
          <Section
            alignItems="stretch"
            gap={0}
            height="fit"
            className="min-w-0 flex-1"
          >
            <Section
              flexDirection="row"
              justifyContent="between"
              alignItems="center"
              gap={1}
              height="fit"
            >
              <Text font="secondary-mono" color="text-03">
                {format.dateTime(new Date(run.time_created), RUN_TIME_FORMAT)}
              </Text>
              <Section
                flexDirection="row"
                alignItems="center"
                gap={0.5}
                padding={0.5}
                width="fit"
                height="fit"
              >
                <Text font="secondary-body" color="text-03">
                  {tRuns(`kinds.${run.kind}`)}
                </Text>
                <KindIcon size={12} className="stroke-text-03" />
              </Section>
            </Section>
            <Section alignItems="stretch" gap={0} padding={0.5} height="fit">
              <Text font="main-ui-body" color="text-04">
                {t(`title.${run.kind}.${cardState(run, group)}`)}
              </Text>
              {description !== null && (
                <Text font="secondary-body" color="text-03" maxLines={3}>
                  {description}
                </Text>
              )}
            </Section>
          </Section>
        </Section>
        {(trace !== null || warnings > 0 || listsChecks) && (
          <Section
            flexDirection="row"
            justifyContent="between"
            alignItems="center"
            gap={1}
            padding={0.5}
            height="fit"
          >
            <Section
              flexDirection="row"
              justifyContent="start"
              alignItems="center"
              gap={1}
              height="fit"
              className="min-w-0 flex-1"
              wrap
            >
              {trace !== null && (
                <Popover>
                  <Popover.Trigger asChild>
                    <Button icon={SvgTextLines} prominence="tertiary" size="xs">
                      {t("tags.stackTrace")}
                    </Button>
                  </Popover.Trigger>
                  <StackTracePopoverContent
                    runId={run.attempt.id}
                    trace={trace}
                  />
                </Popover>
              )}
              {listsDocs ? (
                <Popover>
                  <Popover.Trigger asChild>
                    <Button icon={SvgFileText} prominence="tertiary" size="xs">
                      {docsLabel}
                    </Button>
                  </Popover.Trigger>
                  <FailedDocsPopoverContent
                    ccPairId={ccPairId}
                    indexAttemptId={run.attempt.id}
                    canResolve={resolvable}
                    onResolve={onResolve}
                    resolving={resolving}
                  />
                </Popover>
              ) : run.kind === "checks" && listsChecks ? (
                <Popover>
                  <Popover.Trigger asChild>
                    <Button icon={SvgXOctagon} prominence="tertiary" size="xs">
                      {docsLabel}
                    </Button>
                  </Popover.Trigger>
                  <CheckRunPopoverContent run={run.attempt} beside />
                </Popover>
              ) : (
                warnings > 0 && (
                  <Tag icon={SvgFileText} title={docsLabel} color="gray" />
                )
              )}
            </Section>
            {resolvable && (
              <Button
                icon={SvgCheckAll}
                prominence="tertiary"
                size="xs"
                disabled={resolving}
                onClick={() => onResolve(null)}
              >
                {t("actions.resolve")}
              </Button>
            )}
          </Section>
        )}
      </Section>
    </Card>
  );
}
