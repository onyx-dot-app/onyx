"use client";

import { useNavigation } from "@opal/navigation";
import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { IllustrationContent } from "@opal/layouts";
import SvgNoAccess from "@opal/illustrations/no-access";
import { useUser } from "@/providers/UserProvider";

export default function CraftUpgradePage() {
  const t = useTranslations("craft.upgrade");
  const { isAdmin } = useUser();
  const navigation = useNavigation();

  return (
    <div className="flex h-screen w-full flex-col items-center justify-center gap-4 p-8">
      <IllustrationContent
        illustration={SvgNoAccess}
        title={t("title")}
        description={isAdmin ? t("adminDescription") : t("userDescription")}
      />
      <div className="flex flex-row gap-2">
        <Button prominence="secondary" {...navigation.linkTo("/app")}>
          {t("backToChat.label")}
        </Button>
        {isAdmin && (
          <Button {...navigation.linkTo("/admin/billing")}>
            {t("viewPlans.label")}
          </Button>
        )}
      </div>
    </div>
  );
}
