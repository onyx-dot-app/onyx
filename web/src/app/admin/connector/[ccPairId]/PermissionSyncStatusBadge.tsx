"use client";

import { Tag, Tooltip } from "@opal/components";
import type { TagColor } from "@opal/components";
import type { IconFunctionComponent } from "@opal/types";
import {
  SvgAlertTriangle,
  SvgCheckCircle,
  SvgClock,
  SvgXOctagon,
} from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { PermissionSyncStatusEnum } from "./types";

/**
 * Per-row status badge shown inside both the doc-permission and
 * external-group sync attempt tables in this folder.
 *
 * Functionally equivalent to the legacy `PermissionSyncStatus` component
 * in `web/src/components/Status.tsx`, but built on Opal `Tag` per the
 * `@/components/`-no-import rule (see `.cursor/skills/web/no-legacy-components`).
 *
 * Visual mapping:
 *   - SUCCESS → green Tag, "Succeeded"
 *   - COMPLETED_WITH_ERRORS → amber Tag, "Completed with errors"
 *   - FAILED → amber Tag with XOctagon icon, "Failed" (Opal's `Tag`
 *     palette has no red variant — amber + the Octagon icon is the
 *     closest "danger" treatment available without introducing a new
 *     Tag color)
 *   - IN_PROGRESS → blue Tag, "In Progress"
 *   - NOT_STARTED → gray Tag, "Scheduled"
 *   - null / unknown → gray Tag, "Not Started"
 *
 * Failed and completed-with-errors rows are wrapped in a Tooltip with
 * `errorMsg` when one is supplied — same affordance the legacy badge
 * offered.
 */

interface BadgeConfig {
  color: TagColor;
  icon: IconFunctionComponent;
  label: string;
}

const STATUS_CONFIG: Record<PermissionSyncStatusEnum, BadgeConfig> = {
  [PermissionSyncStatusEnum.SUCCESS]: {
    color: "green",
    icon: SvgCheckCircle,
    label: "Succeeded",
  },
  [PermissionSyncStatusEnum.COMPLETED_WITH_ERRORS]: {
    color: "amber",
    icon: SvgAlertTriangle,
    label: "Completed with errors",
  },
  [PermissionSyncStatusEnum.FAILED]: {
    color: "amber",
    icon: SvgXOctagon,
    label: "Failed",
  },
  [PermissionSyncStatusEnum.IN_PROGRESS]: {
    color: "blue",
    icon: SvgClock,
    label: "In Progress",
  },
  [PermissionSyncStatusEnum.NOT_STARTED]: {
    color: "gray",
    icon: SvgClock,
    label: "Scheduled",
  },
  [PermissionSyncStatusEnum.CANCELED]: {
    color: "gray",
    icon: SvgClock,
    label: "Canceled",
  },
};

const FALLBACK_CONFIG: BadgeConfig = {
  color: "gray",
  icon: SvgClock,
  label: "Not Started",
};

const STATUSES_WITH_ERROR_TOOLTIP: ReadonlySet<PermissionSyncStatusEnum> =
  new Set([
    PermissionSyncStatusEnum.FAILED,
    PermissionSyncStatusEnum.COMPLETED_WITH_ERRORS,
  ]);

interface PermissionSyncStatusBadgeProps {
  status: PermissionSyncStatusEnum | null;
  /** Shown in a tooltip when the status is FAILED or COMPLETED_WITH_ERRORS. */
  errorMsg?: string | null;
}

export function PermissionSyncStatusBadge({
  status,
  errorMsg,
}: PermissionSyncStatusBadgeProps) {
  const config = (status && STATUS_CONFIG[status]) ?? FALLBACK_CONFIG;
  const tag = (
    <Tag color={config.color} icon={config.icon} title={config.label} />
  );

  if (status && STATUSES_WITH_ERROR_TOOLTIP.has(status) && errorMsg) {
    return (
      <Tooltip tooltip={errorMsg} side="bottom">
        <Section width="fit" height="auto" className="cursor-pointer">
          {tag}
        </Section>
      </Tooltip>
    );
  }

  return tag;
}
