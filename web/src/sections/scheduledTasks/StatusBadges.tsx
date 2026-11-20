"use client";

import { useTranslations } from "next-intl";
import { Badge } from "@opal/components";
import {
  SvgAlertCircle,
  SvgCheckCircle,
  SvgClock,
  SvgLoader,
  SvgPauseCircle,
  SvgPlayCircle,
  SvgShield,
  SvgXCircle,
} from "@opal/icons";
import type { IconFunctionComponent, StatusColor } from "@opal/types";
import type { ScheduledTaskStatus } from "@/app/craft/v1/tasks/types";
import type { ScheduledRunStatus } from "@/lib/scheduledTasks/types";

const RUN_STATUS_DISPLAY = {
  QUEUED: { icon: SvgClock, color: "queued" },
  RUNNING: { icon: SvgLoader, color: "info" },
  AWAITING_APPROVAL: { icon: SvgShield, color: "warning" },
  SUCCEEDED: { icon: SvgCheckCircle, color: "success" },
  FAILED: { icon: SvgAlertCircle, color: "error" },
  CANCELLED: { icon: SvgXCircle, color: "default" },
  SKIPPED: { icon: SvgClock, color: "default" },
} satisfies Record<
  ScheduledRunStatus,
  { icon: IconFunctionComponent; color: StatusColor }
>;

interface RunStatusBadgeProps {
  status: ScheduledRunStatus;
}

export function RunStatusBadge({ status }: RunStatusBadgeProps) {
  const t = useTranslations("scheduledTasks");
  const display = RUN_STATUS_DISPLAY[status];
  return (
    <Badge
      icon={display.icon}
      color={display.color}
      title={t("runStatus", { status })}
    />
  );
}

interface TaskStatusBadgeProps {
  status: ScheduledTaskStatus;
}

export function TaskStatusBadge({ status }: TaskStatusBadgeProps) {
  const t = useTranslations("scheduledTasks");
  return (
    <Badge
      icon={status === "ACTIVE" ? SvgPlayCircle : SvgPauseCircle}
      color={status === "ACTIVE" ? "success" : "default"}
      title={t("taskStatus", { status })}
    />
  );
}
