"use client";

import { SvgImage } from "@opal/icons";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import ImageGenerationContent from "./ImageGenerationContent";

export default function Page() {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgImage}
        title="Image Generation"
        description="Settings for in-chat image generation."
      />
      <SettingsLayouts.Body>
        <ImageGenerationContent />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
