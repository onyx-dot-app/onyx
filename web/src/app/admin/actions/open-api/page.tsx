"use client";

import { SvgActions } from "@opal/icons";
import Settings from "@/layouts/settings-layouts";
import OpenApiPageContent from "@/sections/actions/OpenApiPageContent";

export default function Main() {
  return (
    <Settings.Root>
      <Settings.Header
        icon={SvgActions}
        title="OpenAPI Actions"
        description="Connect OpenAPI servers to add custom actions and tools for your assistants."
        separator
      />
      <Settings.Body>
        <OpenApiPageContent />
      </Settings.Body>
    </Settings.Root>
  );
}
