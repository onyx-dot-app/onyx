"use client";

import { useFormatter, useTranslations } from "next-intl";
import { Button, Card, Tag, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import {
  SvgAlertTriangle,
  SvgCheckCircle,
  SvgFileText,
  SvgTextLines,
  SvgXCircle,
} from "@opal/icons";
import type { CardColor, IconFunctionComponent } from "@opal/types";
import type { CCPairRun } from "@/lib/connectors/types";
import type { ActivityGroup } from "@/lib/connectors/ccPair/hooks";
import {
  RUN_KIND_ICONS,
  RUN_TIME_FORMAT,
  isActive,
  runErrorMessage,
  runMinutes,
  runMoved,
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
  group: ActivityGroup,
  active: boolean
): "failed" | "running" | "errors" | "resolved" {
  switch (group) {
    case "failures":
      return "failed";
    case "resolved":
      return "resolved";
    case "errors":
      return active ? "running" : "errors";
  }
}

export interface ActivityCardProps {
  run: CCPairRun;
  group: ActivityGroup;
  onViewTrace: () => void;
}

/** One failed run, or one run with document errors: when, which kind, how it ended, its trace and error count. */
export default function ActivityCard({
  run,
  group,
  onViewTrace,
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

  // A failure explains itself. A run with errors reports what it still did.
  let description: string | null = null;
  if (group === "failures") {
    description = runErrorMessage(run);
  } else if (minutes !== null) {
    description = t(`description.${run.kind}`, {
      count: runMoved(run),
      minutes,
    });
  }

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
                {t(`title.${run.kind}.${cardState(group, active)}`)}
              </Text>
              {description !== null && (
                <Text font="secondary-body" color="text-03" maxLines={3}>
                  {description}
                </Text>
              )}
            </Section>
          </Section>
        </Section>
        {(run.attempt.full_exception_trace !== null || warnings > 0) && (
          <Section
            flexDirection="row"
            justifyContent="start"
            alignItems="center"
            gap={1}
            padding={0.5}
            height="fit"
            wrap
          >
            {run.attempt.full_exception_trace !== null && (
              <Button
                icon={SvgTextLines}
                prominence="tertiary"
                size="xs"
                onClick={onViewTrace}
              >
                {t("tags.stackTrace")}
              </Button>
            )}
            {warnings > 0 && (
              <Tag
                icon={SvgFileText}
                title={
                  group === "resolved"
                    ? t("tags.resolvedDocs", { count: warnings })
                    : t(`tags.${run.kind}`, { count: warnings })
                }
                color="gray"
              />
            )}
          </Section>
        )}
      </Section>
    </Card>
  );
}
