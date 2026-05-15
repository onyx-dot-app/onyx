"use client";

import { cn } from "@opal/utils";
import Text from "@/refresh-components/texts/Text";
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
} from "@/app/craft/v1/tasks/interfaces";

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
      <Text figureSmallLabel text03>
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
  label: string;
  icon: React.FunctionComponent<{ size?: number; className?: string }>;
  className: string;
  iconClassName: string;
}

function getRunStatusDisplay(status: ScheduledTaskRunStatus): RunStatusDisplay {
  switch (status) {
    case "SUCCEEDED":
      return {
        label: "Succeeded",
        icon: SvgCheckCircle,
        className: "bg-status-success-01",
        iconClassName: "text-status-success-05",
      };
    case "FAILED":
      return {
        label: "Failed",
        icon: SvgAlertCircle,
        className: "bg-status-error-01",
        iconClassName: "text-status-error-05",
      };
    case "RUNNING":
      return {
        label: "Running",
        icon: SvgLoader,
        className: "bg-status-info-01",
        iconClassName: "text-status-info-05 animate-spin",
      };
    case "QUEUED":
      return {
        label: "Queued",
        icon: SvgClock,
        className: "bg-background-tint-02",
        iconClassName: "text-text-03",
      };
    case "SKIPPED":
      return {
        label: "Skipped",
        icon: SvgClock,
        className: "bg-background-tint-02",
        iconClassName: "text-text-03",
      };
    case "AWAITING_APPROVAL":
      return {
        label: "Awaiting approval",
        icon: SvgClock,
        className: "bg-status-warning-01",
        iconClassName: "text-status-warning-05",
      };
  }
}

export function RunStatusBadge({ status }: RunStatusBadgeProps) {
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
      <Text figureSmallLabel text03>
        {display.label}
      </Text>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Last-run badge: status badge with relative time, used in list row "Last run".
// ---------------------------------------------------------------------------

export function getRunStatusLabel(status: ScheduledTaskRunStatus): string {
  return getRunStatusDisplay(status).label;
}
