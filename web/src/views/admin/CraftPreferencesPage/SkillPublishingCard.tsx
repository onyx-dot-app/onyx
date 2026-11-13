"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { mutate } from "swr";
import { Card, InputSingleSelect } from "@opal/components";
import { InputHorizontal, Section, toast } from "@opal/layouts";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useSettings } from "@/lib/settings/hooks";
import { PluginPublishingPolicy } from "@/lib/settings/types";
import { updateAdminSettings } from "@/lib/settings/svc";

function isPublishingPolicy(value: string): value is PluginPublishingPolicy {
  return Object.values<string>(PluginPublishingPolicy).includes(value);
}

export default function SkillPublishingCard() {
  const t = useTranslations("admin.craftPreferences.publishing");
  const settings = useSettings();
  const policy = settings.plugin_publishing ?? PluginPublishingPolicy.OPEN;
  const [isSaving, setIsSaving] = useState(false);

  async function save(next: PluginPublishingPolicy) {
    if (next === policy) return;
    setIsSaving(true);
    try {
      await updateAdminSettings({ plugin_publishing: next });
      await mutate(SWR_KEYS.settings);
      toast.success(t("saveSuccess.message"));
    } catch (err) {
      console.error("Failed to save the Publishing setting", err);
      toast.error(err instanceof Error ? err.message : t("saveError.message"));
    } finally {
      setIsSaving(false);
    }
  }

  const descriptions = {
    [PluginPublishingPolicy.OPEN]: t("open.description"),
    [PluginPublishingPolicy.REQUIRES_REVIEW]: t("requiresReview.description"),
    [PluginPublishingPolicy.OFF]: t("off.description"),
  } as const satisfies Record<PluginPublishingPolicy, string>;

  return (
    <Card border="solid" rounding={4}>
      <Section alignItems="stretch" gap={1}>
        <InputHorizontal
          title={t("title")}
          description={descriptions[policy]}
          withLabel
        >
          <InputSingleSelect
            value={policy}
            defaultOption={PluginPublishingPolicy.OPEN}
            placeholder={t("title")}
            disabled={isSaving}
            onValueChange={(value: string) => {
              if (isPublishingPolicy(value)) void save(value);
            }}
            options={[
              { value: PluginPublishingPolicy.OPEN, title: t("open.label") },
              {
                value: PluginPublishingPolicy.REQUIRES_REVIEW,
                title: t("requiresReview.label"),
              },
              { value: PluginPublishingPolicy.OFF, title: t("off.label") },
            ]}
          />
        </InputHorizontal>
      </Section>
    </Card>
  );
}
