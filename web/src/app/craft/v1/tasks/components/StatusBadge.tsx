"use client";

import { useTranslations } from "next-intl";
import { cn } from "@opal/utils";
import { Text } from "@opal/components";
import type { BadgeProps } from "@opal/components";
import {
  SvgAlertCircle,
  SvgCheckCircle,
  SvgClock,
  SvgLoader,
  SvgPauseCircle,
  SvgPlayCircle,
} from "@opal/icons";
import type {
  ScheduledTaskRunStatus,
  ScheduledTaskStatus,
} from "@/app/craft/v1/tasks/types";

// ---------------------------------------------------------------------------
// Task status (active / paused)
// ---------------------------------------------------------------------------

interface TaskStatusBadgeProps {
  status: ScheduledTaskStatus;
}

export function TaskStatusBadge({ status }: TaskStatusBadgeProps) {
  const isActive = status === "ACTIVE";
  const Icon = isActive ? SvgPlayCircle : SvgPauseCircle;
  return (
    <div
      className={cn(
        "inline-flex items-center gap-1 px-1.5 py-0.5 rounded-08",
        isActive ? "bg-status-success-01" : "bg-background-tint-02"
      )}
      data-testid={`task-status-${status}`}
    >
      <Icon
        size={12}
        className={isActive ? "text-status-success-05" : "text-text-03"}
      />
      <Text font="figure-small-label" color="text-03">
        {isActive ? "Active" : "Paused"}
      </Text>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Run status
// ---------------------------------------------------------------------------

interface RunStatusBadgeProps {
  status: ScheduledTaskRunStatus;
}

interface RunStatusDisplay {
  icon: React.FunctionComponent<{ size?: number; className?: string }>;
  className: string;
  iconClassName: string;
}

function getRunStatusDisplay(status: ScheduledTaskRunStatus): RunStatusDisplay {
  switch (status) {
    case "SUCCEEDED":
      return {
        icon: SvgCheckCircle,
        className: "bg-status-success-01",
        iconClassName: "text-status-success-05",
      };
    case "FAILED":
      return {
        icon: SvgAlertCircle,
        className: "bg-status-error-01",
        iconClassName: "text-status-error-05",
      };
    case "RUNNING":
      return {
        icon: SvgLoader,
        className: "bg-status-info-01",
        iconClassName: "text-status-info-05 animate-spin",
      };
    case "QUEUED":
      return {
        icon: SvgClock,
        className: "bg-background-tint-02",
        iconClassName: "text-text-03",
      };
    case "CANCELLED":
      return {
        icon: SvgClock,
        className: "bg-background-tint-02",
        iconClassName: "text-text-03",
      };
    case "SKIPPED":
      return {
        icon: SvgClock,
        className: "bg-background-tint-02",
        iconClassName: "text-text-03",
      };
    case "AWAITING_APPROVAL":
      return {
        icon: SvgClock,
        className: "bg-status-warning-01",
        iconClassName: "text-status-warning-05",
      };
  }
}

export function RunStatusBadge({ status }: RunStatusBadgeProps) {
  const t = useTranslations("scheduledTasks");
  const display = getRunStatusDisplay(status);
  const Icon = display.icon;
  return (
    <div
      className={cn(
        "inline-flex items-center gap-1 px-1.5 py-0.5 rounded-08",
        display.className
      )}
      data-testid={`run-status-${status}`}
    >
      <Icon size={12} className={display.iconClassName} />
      <Text font="figure-small-label" color="text-03">
        {t("runStatus", { status })}
      </Text>
    </div>
  );
}
