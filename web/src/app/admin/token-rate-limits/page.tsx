"use client";

import { redirect } from "next/navigation";
import type { Route } from "next";
import { EE_ENABLED } from "@/lib/constants";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { SettingsLayouts } from "@opal/layouts";
import TokenRateLimitsPanel from "./TokenRateLimitsPanel";

export default function Page() {
  if (EE_ENABLED) {
    redirect(ADMIN_ROUTES.USAGE.path as Route);
  }

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        title={ADMIN_ROUTES.TOKEN_RATE_LIMITS.title}
        icon={ADMIN_ROUTES.TOKEN_RATE_LIMITS.icon}
        divider
      />
      <SettingsLayouts.Body>
        <TokenRateLimitsPanel />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
