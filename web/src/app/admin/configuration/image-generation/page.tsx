"use client";

import * as SettingsLayouts from "@/layouts/settings-layouts";
import ImageGenerationContent from "./ImageGenerationContent";
import { ADMIN_ROUTE_CONFIG, ADMIN_PATHS } from "@/lib/admin-routes";

const route = ADMIN_ROUTE_CONFIG[ADMIN_PATHS.IMAGE_GENERATION]!;

export default function Page() {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={route.title}
        description="Settings for in-chat image generation."
      />
      <SettingsLayouts.Body>
        <ImageGenerationContent />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
