"use client";

import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import {
  SvgAlertCircle,
  SvgCheckCircle,
  SvgClock,
  SvgLoader,
  SvgPauseCircle,
  SvgPlayCircle,
  SvgUserCheck,
} from "@opal/icons";
import { cn } from "@opal/utils";
import type { IconComponent } from "@/app/flows/components/nodeVisuals";
import type { FlowRunStatus, FlowStatus } from "@/app/flows/types";

interface BadgeLook {
  icon: IconComponent;
  chipClassName: string;
  iconClassName: string;
}

function Badge({
  look,
  label,
  testId,
}: {
  look: BadgeLook;
  label: string;
  testId: string;
}) {
  const Icon = look.icon;
  return (
    <div
      className={cn(
        "inline-flex items-center gap-1 px-1.5 py-0.5 rounded-08",
        look.chipClassName
      )}
      data-testid={testId}
    >
      <Icon size={12} className={look.iconClassName} />
      <Text font="figure-small-label" color="text-03">
        {label}
      </Text>
    </div>
  );
}

export function FlowStatusBadge({ status }: { status: FlowStatus }) {
  const t = useTranslations("flows.status");
  const active = status === "ACTIVE";

  return (
    <Badge
      testId={`flow-status-${status}`}
      label={active ? t("active") : t("paused")}
      look={{
        icon: active ? SvgPlayCircle : SvgPauseCircle,
        chipClassName: active
          ? "bg-status-success-01"
          : "bg-background-tint-02",
        iconClassName: active ? "text-status-success-05" : "text-text-03",
      }}
    />
  );
}

function runLook(status: FlowRunStatus): BadgeLook {
  switch (status) {
    case "SUCCEEDED":
      return {
        icon: SvgCheckCircle,
        chipClassName: "bg-status-success-01",
        iconClassName: "text-status-success-05",
      };
    case "FAILED":
      return {
        icon: SvgAlertCircle,
        chipClassName: "bg-status-error-01",
        iconClassName: "text-status-error-05",
      };
    case "RUNNING":
      return {
        icon: SvgLoader,
        chipClassName: "bg-status-info-01",
        iconClassName: "text-status-info-05 animate-spin",
      };
    case "AWAITING_DECISION":
      // Warning rather than info: the run is not progressing, and somebody
      // has to do something about that.
      return {
        icon: SvgUserCheck,
        chipClassName: "bg-status-warning-01",
        iconClassName: "text-status-warning-05",
      };
    case "QUEUED":
    case "SKIPPED":
      return {
        icon: SvgClock,
        chipClassName: "bg-background-tint-02",
        iconClassName: "text-text-03",
      };
  }
}

export function RunStatusBadge({ status }: { status: FlowRunStatus }) {
  const t = useTranslations("flows.runStatus");
  return (
    <Badge
      testId={`run-status-${status}`}
      label={t(status)}
      look={runLook(status)}
    />
  );
}
