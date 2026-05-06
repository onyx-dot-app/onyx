"use client";

import { useCallback } from "react";
import { mutate } from "swr";
import { ContentAction } from "@opal/layouts";
import Card from "@/refresh-components/cards/Card";
import Switch from "@/refresh-components/inputs/Switch";
import { useSettingsContext } from "@/providers/SettingsProvider";
import { SWR_KEYS } from "@/lib/swr-keys";
import { toast } from "@/hooks/useToast";
import { Settings } from "@/interfaces/settings";

export default function InviteOnlyCard() {
  const settingsContext = useSettingsContext();
  const settings = settingsContext.settings;

  const saveSettings = useCallback(
    async (updates: Partial<Settings>) => {
      const newSettings = { ...settings, ...updates };
      try {
        const response = await fetch("/api/admin/settings", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(newSettings),
        });
        if (!response.ok) {
          const errorMsg = (await response.json()).detail;
          throw new Error(errorMsg);
        }
        await mutate(SWR_KEYS.settings);
        toast.success("Settings updated");
      } catch {
        toast.error("Failed to update settings");
      }
    },
    [settings]
  );

  return (
    <Card gap={0.5} padding={0.75}>
      <ContentAction
        title="Restrict Open Sign-Up"
        description="New users must be invited to join this workspace."
        sizePreset="main-ui"
        variant="section"
        padding="fit"
        rightChildren={
          <Switch
            checked={settings.invite_only_enabled ?? false}
            onCheckedChange={(checked) =>
              void saveSettings({ invite_only_enabled: checked })
            }
          />
        }
      />
    </Card>
  );
}
