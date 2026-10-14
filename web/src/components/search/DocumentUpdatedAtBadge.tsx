"use client";

import { useLocale, useTranslations } from "next-intl";
import { timeAgo } from "@opal/time";
import { MetadataBadge } from "../MetadataBadge";

export function DocumentUpdatedAtBadge({
  updatedAt,
  modal,
}: {
  updatedAt: string;
  modal?: boolean;
}) {
  const t = useTranslations("common.documentDisplay");
  const locale = useLocale();
  const relative = timeAgo(updatedAt, locale) ?? "";
  return (
    <MetadataBadge
      flexNone={modal}
      value={modal ? relative : t("updated.text", { date: relative })}
    />
  );
}
