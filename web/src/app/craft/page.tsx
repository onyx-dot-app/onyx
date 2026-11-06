"use client";

import { useNavigation } from "@opal/navigation";
import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { CRAFT_PATH } from "@/app/craft/v1/constants";

/**
 * Build Page - Redirects to the new Build V1 page
 *
 * The new Build experience is at /craft/v1
 * This page exists for backwards compatibility.
 */
export default function BuildPage() {
  const t = useTranslations("craft.redirect");
  const navigation = useNavigation();

  useEffect(() => {
    navigation.go(CRAFT_PATH, { replace: true });
  }, [navigation]);

  return (
    <div className="flex items-center justify-center h-screen">
      <div className="animate-pulse text-text-03">{t("redirecting.label")}</div>
    </div>
  );
}
