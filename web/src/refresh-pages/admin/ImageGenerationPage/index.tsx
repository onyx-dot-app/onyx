"use client";

import { SettingsLayouts } from "@opal/layouts";
import ImageGenerationContent from "@/refresh-pages/admin/ImageGenerationPage/ImageGenerationContent";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useTranslation } from "react-i18next";
import { useAdminPageTitle } from "@/lib/admin-i18n";

const route = ADMIN_ROUTES.IMAGE_GENERATION;

export default function ImageGenerationPage() {
  const { t } = useTranslation();
  const title = useAdminPageTitle(route);
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={title}
        description={t("admin.image_gen.desc", "Settings for in-chat image generation.")}
        divider
      />
      <SettingsLayouts.Body>
        <ImageGenerationContent />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
