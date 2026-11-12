"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Card, InputSingleSelect, Text } from "@opal/components";
import { Content, Section } from "@opal/layouts";
import { SvgBlocks, SvgMinusCircle } from "@opal/icons";
import type { SkillInstallationPolicy } from "@/lib/skills/types";
import type { UserGroupPlugin } from "@/lib/groupPlugins/types";
import {
  INHERIT,
  isPolicyChoice,
  useGroupPolicyOptions,
  type PolicyChoice,
} from "@/lib/skills/installationPolicy";

interface GroupPluginSettingRowProps {
  plugin: UserGroupPlugin;
  onSave: (
    pluginId: string,
    policy: SkillInstallationPolicy | null
  ) => Promise<boolean>;
}

/** One plugin of the group. A change saves at once, apart from the group form. */
export default function GroupPluginSettingRow({
  plugin,
  onSave,
}: GroupPluginSettingRowProps) {
  const t = useTranslations("admin.groups.plugins");
  const { options, policyLabel } = useGroupPolicyOptions(
    plugin.company_installation_policy
  );
  const [saving, setSaving] = useState(false);
  const saved: PolicyChoice = plugin.installation_policy ?? INHERIT;
  const settingOnly = plugin.permission === null;

  async function save(next: PolicyChoice) {
    if (saving || next === saved) return;
    setSaving(true);
    try {
      await onSave(plugin.plugin_id, next === INHERIT ? null : next);
    } finally {
      setSaving(false);
    }
  }

  const access = settingOnly
    ? t("row.settingOnly")
    : plugin.published
      ? t("row.sharedPublished")
      : t("row.shared");
  const status =
    saved === INHERIT
      ? t("row.inherited", {
          policy: policyLabel(plugin.company_installation_policy),
        })
      : t("row.overridden", {
          policy: policyLabel(saved),
          company: policyLabel(plugin.company_installation_policy),
        });

  return (
    <Card border="solid" rounding={3} padding={3}>
      <Section
        role="group"
        aria-label={plugin.name}
        alignItems="stretch"
        height="auto"
        gap={2}
      >
        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems="start"
          wrap
          height="auto"
          gap={3}
        >
          <Section
            width="auto"
            height="auto"
            alignItems="start"
            className="min-w-0 max-w-full grow basis-60"
          >
            <Content
              icon={SvgBlocks}
              title={plugin.name}
              description={plugin.description || undefined}
              font="main-ui-action"
              descriptionMaxLines={2}
            />
          </Section>
          <Section
            flexDirection="row"
            width="auto"
            height="auto"
            alignItems="center"
            gap={1}
            className="min-w-0 max-w-full grow basis-60"
          >
            <Section width="full" height="auto" alignItems="stretch">
              <InputSingleSelect
                placeholder={t("row.select", { name: plugin.name })}
                value={saved}
                defaultOption={INHERIT}
                options={options}
                disabled={!plugin.can_edit || saving}
                onValueChange={(value) => {
                  if (isPolicyChoice(value)) void save(value);
                }}
              />
            </Section>
            {settingOnly && plugin.can_edit && (
              <Button
                icon={SvgMinusCircle}
                prominence="tertiary"
                tooltip={t("row.remove", { name: plugin.name })}
                aria-label={t("row.remove", { name: plugin.name })}
                disabled={saving}
                onClick={() => void save(INHERIT)}
              />
            )}
          </Section>
        </Section>
        <Text font="secondary-body" color="text-03" as="p">
          {`${access} · ${status}`}
        </Text>
        {!plugin.can_edit && (
          <Text font="secondary-body" color="text-03" as="p">
            {t("row.readOnly")}
          </Text>
        )}
      </Section>
    </Card>
  );
}
