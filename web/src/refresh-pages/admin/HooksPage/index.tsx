"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useSettingsContext } from "@/providers/SettingsProvider";
import { toast } from "@/hooks/useToast";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import HooksContent from "./HooksContent";

const route = ADMIN_ROUTES.HOOKS;

export default function HooksPage() {
  const router = useRouter();
  const { settings, settingsLoading } = useSettingsContext();

  useEffect(() => {
    if (!settingsLoading && !settings.hooks_enabled) {
      toast.info("Hook Extensions are not enabled for this deployment.");
      router.replace("/");
    }
  }, [settingsLoading, settings.hooks_enabled, router]);

  if (settingsLoading || !settings.hooks_enabled) {
    return <SimpleLoader />;
  }

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={route.title}
        description="Extend Onyx pipelines by registering external API endpoints as callbacks at predefined hook points."
        separator
      />
      <SettingsLayouts.Body>
        <HooksContent />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
