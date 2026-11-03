"use client";

import { useTranslations } from "next-intl";
import { Badge, type BadgeSize } from "@opal/components";
import type { StatusTag } from "@/views/admin/connectors/ConnectorDetailPage/statusTag";

interface StatusTagPillProps {
  tag: StatusTag;
  size?: BadgeSize;
}

/** A pair's or run's status pill: the state's icon and tint with a text-04 label. */
export default function StatusTagPill({ tag, size }: StatusTagPillProps) {
  const tBadges = useTranslations("admin.status.badges");
  return (
    <Badge
      icon={tag.icon}
      title={tBadges(tag.labelKey)}
      color={tag.color}
      textColor="text-04"
      size={size}
    />
  );
}
