"use client";

import { useTranslations } from "next-intl";
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

/** Message keys inside the `admin.connector` namespace. */
type BadgeLabelKey =
  | "permissionSyncStatus.success.label"
  | "permissionSyncStatus.completedWithErrors.label"
  | "permissionSyncStatus.failed.label"
  | "permissionSyncStatus.inProgress.label"
  | "permissionSyncStatus.notStarted.label"
  | "permissionSyncStatus.canceled.label"
  | "permissionSyncStatus.fallback.label";

interface BadgeConfig {
  color: TagColor;
  icon: IconFunctionComponent;
  labelKey: BadgeLabelKey;
}

const STATUS_CONFIG: Record<PermissionSyncStatusEnum, BadgeConfig> = {
  [PermissionSyncStatusEnum.SUCCESS]: {
    color: "green",
    icon: SvgCheckCircle,
    labelKey: "permissionSyncStatus.success.label",
  },
  [PermissionSyncStatusEnum.COMPLETED_WITH_ERRORS]: {
    color: "amber",
    icon: SvgAlertTriangle,
    labelKey: "permissionSyncStatus.completedWithErrors.label",
  },
  [PermissionSyncStatusEnum.FAILED]: {
    color: "amber",
    icon: SvgXOctagon,
    labelKey: "permissionSyncStatus.failed.label",
  },
  [PermissionSyncStatusEnum.IN_PROGRESS]: {
    color: "blue",
    icon: SvgClock,
    labelKey: "permissionSyncStatus.inProgress.label",
  },
  [PermissionSyncStatusEnum.NOT_STARTED]: {
    color: "gray",
    icon: SvgClock,
    labelKey: "permissionSyncStatus.notStarted.label",
  },
  [PermissionSyncStatusEnum.CANCELED]: {
    color: "gray",
    icon: SvgClock,
    labelKey: "permissionSyncStatus.canceled.label",
  },
};

const FALLBACK_CONFIG: BadgeConfig = {
  color: "gray",
  icon: SvgClock,
  labelKey: "permissionSyncStatus.fallback.label",
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
  const t = useTranslations("admin.connector");
  const config = (status && STATUS_CONFIG[status]) ?? FALLBACK_CONFIG;
  const tag = (
    <Tag color={config.color} icon={config.icon} title={t(config.labelKey)} />
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
