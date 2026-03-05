"use client";

import * as SettingsLayouts from "@/layouts/settings-layouts";
import OpenApiPageContent from "@/sections/actions/OpenApiPageContent";
import { ADMIN_ROUTE_CONFIG, ADMIN_PATHS } from "@/lib/admin-routes";

const route = ADMIN_ROUTE_CONFIG[ADMIN_PATHS.OPENAPI_ACTIONS]!;

export default function Main() {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={route.title}
        description="Connect OpenAPI servers to add custom actions and tools for your agents."
        separator
      />
      <SettingsLayouts.Body>
        <OpenApiPageContent />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
