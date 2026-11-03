"use client";

import { useTranslations } from "next-intl";
import { Badge, type BadgeSize } from "@opal/components";
import type { StatusTag } from "@/views/admin/connectors/ConnectorDetailPage/statusTag";

interface StatusTagPillProps {
  tag: StatusTag;
  size?: BadgeSize;
  /** Makes the pill a button, named by its tooltip. */
  action?: { tooltip: string; onClick: () => void };
}

/** A pair's or run's status pill: the state's icon and tint with a text-04 label. */
export default function StatusTagPill({
  tag,
  size,
  action,
}: StatusTagPillProps) {
  const tBadges = useTranslations("admin.status.badges");
  const props = {
    icon: tag.icon,
    title: tBadges(tag.labelKey),
    color: tag.color,
    textColor: "text-04",
    size,
  } as const;
  // Badge takes `tooltip` and `onClick` together or not at all.
  return action === undefined ? (
    <Badge {...props} />
  ) : (
    <Badge {...props} {...action} />
  );
}
