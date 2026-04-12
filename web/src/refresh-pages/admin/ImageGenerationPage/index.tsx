"use client";

import { useTranslations } from "next-intl";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import ImageGenerationContent from "@/refresh-pages/admin/ImageGenerationPage/ImageGenerationContent";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

const route = ADMIN_ROUTES.IMAGE_GENERATION;

export default function ImageGenerationPage() {
  const t = useTranslations("admin.imageGeneration");

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={route.title}
        description={t("description")}
        separator
      />
      <SettingsLayouts.Body>
        <ImageGenerationContent />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
