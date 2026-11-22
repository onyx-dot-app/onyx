"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import { InputSingleSelect } from "@opal/components";
import { toast } from "@opal/layouts";
import { setIntegrationInstallationPolicy } from "@/lib/integrations/svc";
import type { AdminIntegration } from "@/lib/integrations/types";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import {
  useInstallationPolicyCopy,
  usePolicyOptions,
} from "@/lib/skills/hooks";
import { INSTALLATION_POLICIES } from "@/lib/skills/installationPolicy";
import { SWR_KEYS } from "@/lib/swr-keys";
import { Permission } from "@/lib/types";

interface IntegrationInstallSettingProps {
  integration: Pick<AdminIntegration, "id" | "name" | "installation_policy">;
}

/** The company install setting of an integration. Only an organization-wide
 * action manager changes it. Not available keeps the integration private:
 * only its owner and its shares use it. */
export default function IntegrationInstallSetting({
  integration,
}: IntegrationInstallSettingProps) {
  const t = useTranslations("admin.integrations.installation");
  const { mutate } = useSWRConfig();
  const { isGlobalHolder } = usePermissionAuthority(Permission.MANAGE_ACTIONS);
  const policyCopy = useInstallationPolicyCopy();
  // An integration that is Not available stays in use by its owner, its
  // shares and the groups with their own setting.
  const policyOptions = usePolicyOptions().map((option) =>
    option.value === "NOT_AVAILABLE"
      ? { ...option, description: t("notAvailable") }
      : option.value === "REQUIRED"
        ? { ...option, description: t("required") }
        : option
  );
  const [saving, setSaving] = useState(false);
  const policy = integration.installation_policy;

  async function save(next: AdminIntegration["installation_policy"]) {
    setSaving(true);
    try {
      await setIntegrationInstallationPolicy(integration.id, next);
      toast.success(
        t("saved", { name: integration.name, policy: policyCopy.label(next) })
      );
    } catch (saveError) {
      toast.error(
        saveError instanceof Error ? saveError.message : t("saveFailed")
      );
    }
    try {
      await Promise.all([
        mutate(SWR_KEYS.adminIntegrations),
        mutate(SWR_KEYS.adminIntegration(integration.id)),
        mutate(SWR_KEYS.integrations),
      ]);
    } finally {
      setSaving(false);
    }
  }

  return (
    <InputSingleSelect
      placeholder={t("select", { name: integration.name })}
      value={policy}
      disabled={!isGlobalHolder || saving}
      options={policyOptions}
      onValueChange={(value) => {
        const next = INSTALLATION_POLICIES.find((option) => option === value);
        if (next && next !== policy) void save(next);
      }}
    />
  );
}
