"use client";

import { useTranslations } from "next-intl";
import { SettingsLayouts } from "@opal/layouts";
import ImageGenerationContent from "@/views/admin/ImageGenerationPage/ImageGenerationContent";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

const route = ADMIN_ROUTES.IMAGE_GENERATION;

export default function ImageGenerationPage() {
  const t = useTranslations("admin.imageGeneration");

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={t("header.title")}
        description={t("header.description")}
        divider
      />
      <SettingsLayouts.Body>
        <ImageGenerationContent />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
