"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import { toast } from "@opal/layouts";
import useShareableGroups, {
  type MinimalUserGroupSnapshot,
} from "@/hooks/useShareableGroups";
import { setIntegrationGroupSettings } from "@/lib/integrations/svc";
import type {
  AdminIntegrationDetail,
  IntegrationGroupSettingChange,
} from "@/lib/integrations/types";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import {
  fromPolicyChoice,
  INHERIT,
  type PolicyChoice,
} from "@/lib/skills/installationPolicy";
import { groupAccessRows, type GroupSettingRow } from "@/lib/skills/sharing";
import { SWR_KEYS } from "@/lib/swr-keys";
import { Permission } from "@/lib/types";
import SkillGroupAccess from "@/sections/modals/skills/SkillGroupAccess";

interface IntegrationGroupAccessProps {
  integration: AdminIntegrationDetail;
}

/** Claude's per-group install setting override. Only an organization-wide
 * action manager sees it. Each change saves at once. */
export default function IntegrationGroupAccess({
  integration,
}: IntegrationGroupAccessProps) {
  const t = useTranslations("admin.integrations.groupAccess");
  const tInstall = useTranslations("admin.integrations.installation");
  const { mutate } = useSWRConfig();
  const { isGlobalHolder } = usePermissionAuthority(Permission.MANAGE_ACTIONS);
  const { data: groups } = useShareableGroups();
  // A group added here has no setting until an admin chooses one.
  const [added, setAdded] = useState<GroupSettingRow[]>([]);
  const [saving, setSaving] = useState(false);

  if (!isGlobalHolder) return null;

  const stored: GroupSettingRow[] = integration.group_settings.map(
    (setting) => ({
      group_id: setting.group_id,
      group_name: setting.group_name,
      choice: setting.installation_policy,
    })
  );
  const storedIds = new Set(stored.map((row) => row.group_id));
  const rows = groupAccessRows(
    [...stored, ...added.filter((row) => !storedIds.has(row.group_id))],
    integration.group_shares.map((share) => ({
      ...share,
      permission: "VIEWER" as const,
    }))
  );

  async function save(change: IntegrationGroupSettingChange) {
    setSaving(true);
    try {
      await setIntegrationGroupSettings(integration.id, [change]);
      // Read the detail again: another control can save after this request.
      await mutate(SWR_KEYS.adminIntegration(integration.id));
      setAdded((current) =>
        current.filter((row) => row.group_id !== change.group_id)
      );
      void mutate(SWR_KEYS.integrations);
      toast.success(t("saved", { name: integration.name }));
    } catch (saveError) {
      toast.error(
        saveError instanceof Error ? saveError.message : t("saveFailed")
      );
    } finally {
      setSaving(false);
    }
  }

  function choose(groupId: number, choice: PolicyChoice) {
    const isStored = storedIds.has(groupId);
    if (choice === INHERIT && !isStored) return;
    void save({
      group_id: groupId,
      installation_policy: fromPolicyChoice(choice),
    });
  }

  function add(group: MinimalUserGroupSnapshot) {
    setAdded((current) => [
      ...current,
      { group_id: group.id, group_name: group.name, choice: INHERIT },
    ]);
  }

  function remove(groupId: number) {
    if (!storedIds.has(groupId)) {
      setAdded((current) => current.filter((row) => row.group_id !== groupId));
      return;
    }
    void save({ group_id: groupId, installation_policy: null });
  }

  return (
    <SkillGroupAccess
      rows={rows}
      company={integration.installation_policy}
      groups={groups ?? []}
      disabled={saving}
      onChoice={choose}
      onAdd={add}
      onRemove={remove}
      requiredDescription={tInstall("required")}
    />
  );
}
