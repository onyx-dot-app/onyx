"use client";

import { SvgImage } from "@opal/icons";
import { AdminPageLayout } from "@/refresh-components/layouts/AdminPageLayout";
import ImageGenerationContent from "./ImageGenerationContent";

export default function Page() {
  return (
    <AdminPageLayout
      icon={SvgImage}
      title="Image Generation"
      description="Settings for in-chat image generation."
    >
      <ImageGenerationContent />
    </AdminPageLayout>
  );
}
