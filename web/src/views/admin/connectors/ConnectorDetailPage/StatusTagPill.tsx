"use client";

import { useTranslations } from "next-intl";
import { Badge, BadgeButton, type BadgeSize } from "@opal/components";
import type { StatusTag } from "@/views/admin/connectors/ConnectorDetailPage/statusTag";

interface StatusTagPillProps {
  tag: StatusTag;
  size?: BadgeSize;
  /** Hover text on a static pill. Badge owns it, so no `Tooltip` wraps the pill. */
  tooltip?: string;
  /** Makes the pill a button, named by its tooltip. */
  action?: { tooltip: string; onClick: () => void };
}

/** A pair's or run's status pill: the state's icon and tint with a text-04 label. */
export default function StatusTagPill({
  tag,
  size,
  tooltip,
  action,
}: StatusTagPillProps) {
  const tBadges = useTranslations("admin.status.badges");
  const props = {
    icon: tag.icon,
    title: tBadges(tag.labelKey),
    color: tag.color,
    titleColor: "text-04",
    size,
  } as const;
  return action === undefined ? (
    <Badge {...props} tooltip={tooltip} />
  ) : (
    <BadgeButton {...props} {...action} />
  );
}
