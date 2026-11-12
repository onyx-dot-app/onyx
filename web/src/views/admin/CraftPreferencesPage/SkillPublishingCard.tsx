"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import useSWR, { mutate } from "swr";
import { Card, InputSingleSelect, InputSwitch } from "@opal/components";
import { InputHorizontal, Section, toast } from "@opal/layouts";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useSettings } from "@/lib/settings/hooks";
import { PluginPublishingPolicy } from "@/lib/settings/types";
import { updateAdminSettings } from "@/lib/settings/svc";
import { setOrganizationLibraryDefaultAccess } from "@/lib/skills/api";
import { useInstallationPolicyCopy } from "@/lib/skills/installationPolicy";
import type {
  OrganizationLibraryDefaultAccess,
  OrganizationLibraryDefaultPolicy,
} from "@/lib/skills/types";

const DEFAULT_ACCESS_POLICIES = [
  "AVAILABLE",
  "DEFAULT",
  "NOT_AVAILABLE",
] as const satisfies readonly OrganizationLibraryDefaultPolicy[];

function isPublishingPolicy(value: string): value is PluginPublishingPolicy {
  return Object.values<string>(PluginPublishingPolicy).includes(value);
}

function isDefaultAccessPolicy(
  value: string
): value is OrganizationLibraryDefaultPolicy {
  return DEFAULT_ACCESS_POLICIES.some((policy) => policy === value);
}

/** The admin skill policies: Publishing, Default access of the Organization
 * library, and Sharing. */
export default function SkillPublishingCard() {
  const t = useTranslations("admin.craftPreferences.publishing");
  const settings = useSettings();
  const policy = settings.plugin_publishing ?? PluginPublishingPolicy.OPEN;
  const sharing = settings.plugin_sharing ?? true;
  const { data: defaultAccess } = useSWR<OrganizationLibraryDefaultAccess>(
    SWR_KEYS.organizationLibraryDefaultAccess,
    errorHandlingFetcher
  );
  const [isSaving, setIsSaving] = useState(false);
  const policyCopy = useInstallationPolicyCopy();

  async function saveSetting(
    run: () => Promise<void>,
    key: string,
    success: string,
    failure: string
  ) {
    setIsSaving(true);
    try {
      await run();
      await mutate(key);
      toast.success(success);
    } catch (err) {
      console.error("Failed to save a skill setting", err);
      toast.error(err instanceof Error ? err.message : failure);
    } finally {
      setIsSaving(false);
    }
  }

  async function save(next: PluginPublishingPolicy) {
    if (next === policy) return;
    await saveSetting(
      () => updateAdminSettings({ plugin_publishing: next }),
      SWR_KEYS.settings,
      t("saveSuccess.message"),
      t("saveError.message")
    );
  }

  async function saveDefaultAccess(next: OrganizationLibraryDefaultPolicy) {
    if (next === defaultAccess?.installation_policy) return;
    await saveSetting(
      async () => {
        await setOrganizationLibraryDefaultAccess(next);
      },
      SWR_KEYS.organizationLibraryDefaultAccess,
      t("defaultAccess.saveSuccess.message"),
      t("defaultAccess.saveError.message")
    );
  }

  async function saveSharing(next: boolean) {
    await saveSetting(
      () => updateAdminSettings({ plugin_sharing: next }),
      SWR_KEYS.settings,
      t("sharing.saveSuccess.message"),
      t("sharing.saveError.message")
    );
  }

  const descriptions = {
    [PluginPublishingPolicy.OPEN]: t("open.description"),
    [PluginPublishingPolicy.REQUIRES_REVIEW]: t("requiresReview.description"),
    [PluginPublishingPolicy.OFF]: t("off.description"),
  } as const satisfies Record<PluginPublishingPolicy, string>;

  const currentDefault = defaultAccess?.installation_policy ?? "AVAILABLE";

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
        <InputHorizontal
          title={t("defaultAccess.title")}
          description={t("defaultAccess.description", {
            setting: policyCopy.description(currentDefault),
          })}
          withLabel
        >
          <InputSingleSelect
            value={currentDefault}
            defaultOption="AVAILABLE"
            placeholder={t("defaultAccess.title")}
            disabled={isSaving || defaultAccess === undefined}
            onValueChange={(value: string) => {
              if (isDefaultAccessPolicy(value)) void saveDefaultAccess(value);
            }}
            options={DEFAULT_ACCESS_POLICIES.map((value) => ({
              value,
              title: policyCopy.label(value),
            }))}
          />
        </InputHorizontal>
        <InputHorizontal
          title={t("sharing.title")}
          description={t("sharing.description")}
          withLabel
        >
          <InputSwitch
            checked={sharing}
            disabled={isSaving}
            onCheckedChange={(checked: boolean) => void saveSharing(checked)}
          />
        </InputHorizontal>
      </Section>
    </Card>
  );
}
