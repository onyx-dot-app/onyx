"use client";

import { useTranslations } from "next-intl";
import { Tag } from "@opal/components";
import type { StatusTag } from "@/views/admin/connectors/ConnectorDetailPage/statusTag";

interface StatusTagPillProps {
  tag: StatusTag;
}

/** A pair's or run's status pill: the state's icon and tint with a text-04 label. */
export default function StatusTagPill({ tag }: StatusTagPillProps) {
  const tBadges = useTranslations("admin.status.badges");
  return (
    <Tag
      icon={tag.icon}
      title={tBadges(tag.labelKey)}
      color={tag.color}
      variant="status"
      font="secondary-body"
    />
  );
}
