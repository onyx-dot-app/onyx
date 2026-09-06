"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import type { Route } from "next";
import { Button } from "@opal/components";
import { SvgArrowLeft } from "@opal/icons";

export interface BackButtonProps {
  behaviorOverride?: () => void;
  routerOverride?: string;
}

export default function BackButton({
  behaviorOverride,
  routerOverride,
}: BackButtonProps) {
  const t = useTranslations("common.backButton");
  const router = useRouter();

  return (
    <Button
      icon={SvgArrowLeft}
      prominence="tertiary"
      onClick={() => {
        if (behaviorOverride) {
          behaviorOverride();
        } else if (routerOverride) {
          router.push(routerOverride as Route);
        } else {
          router.back();
        }
      }}
    >
      {t("label")}
    </Button>
  );
}
