"use client";

import { useLocale, useTranslations } from "next-intl";
import { timeAgo } from "@opal/time";
import { MetadataBadge } from "../MetadataBadge";

export function DocumentUpdatedAtBadge({ updatedAt }: { updatedAt: string }) {
  const t = useTranslations("common.documentDisplay");
  const locale = useLocale();
  const relative = timeAgo(updatedAt, locale) ?? "";
  return <MetadataBadge value={t("updated.text", { date: relative })} />;
}
