"use client";

import { useTranslations } from "next-intl";
import { MessageCard } from "@opal/components";

/** The admin turned off sharing with people and groups. */
export default function SharingOffNotice() {
  const t = useTranslations("skills.modals.share.sharingOff");
  return (
    <MessageCard
      variant="info"
      outerPadding={1}
      innerPadding={1}
      title={t("title")}
      description={t("description")}
    />
  );
}
