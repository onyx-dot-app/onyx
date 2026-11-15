"use client";

import { useNavigation } from "@opal/navigation";
import { useTranslations } from "next-intl";
import type { Route } from "next";
import { Button } from "@opal/components";
import { SvgArrowLeft } from "@opal/icons";

export interface BackButtonProps {
  behaviorOverride?: () => void;
  routerOverride?: Route;
  /** Where Back goes when the previous page is not in the app. */
  fallback?: Route;
}

export default function BackButton({
  behaviorOverride,
  routerOverride,
  fallback = "/app",
}: BackButtonProps) {
  const t = useTranslations("common.backButton");
  const navigation = useNavigation();

  return (
    <Button
      icon={SvgArrowLeft}
      prominence="tertiary"
      onClick={() => {
        if (behaviorOverride) {
          behaviorOverride();
        } else if (routerOverride) {
          navigation.go(routerOverride);
        } else {
          navigation.clampedBack(fallback);
        }
      }}
    >
      {t("label")}
    </Button>
  );
}
