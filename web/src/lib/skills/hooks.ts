import { useTranslations } from "next-intl";
import type { SelectOption } from "@opal/components";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { useSettings } from "@/lib/settings/hooks";
import { PluginPublishingPolicy } from "@/lib/settings/types";
import { Permission } from "@/lib/types";
import {
  INHERIT,
  INSTALLATION_POLICIES,
  type InheritOption,
} from "@/lib/skills/installationPolicy";
import type { SkillInstallationPolicy } from "@/lib/skills/types";

export type PublishAction = "publish" | "review" | "off";

/** What publishing a skill does for the current user. */
export function usePublishAction(): PublishAction {
  const { isGlobalHolder } = usePermissionAuthority(Permission.MANAGE_PLUGINS);
  const { plugin_publishing: policy } = useSettings();
  if (isGlobalHolder) return "publish";
  if (policy === PluginPublishingPolicy.REQUIRES_REVIEW) return "review";
  if (policy === PluginPublishingPolicy.OFF) return "off";
  return "publish";
}

/** Sharing with people and groups is allowed for the current user: the admin
 * Sharing setting is on, or the user is an organization-wide skill manager. */
export function useSharingAllowed(): boolean {
  const { isGlobalHolder } = usePermissionAuthority(Permission.MANAGE_PLUGINS);
  const { plugin_sharing: sharing } = useSettings();
  return isGlobalHolder || sharing !== false;
}

/** The one set of level labels and help text. ``null`` is "no own setting":
 * a group uses the Organization setting, and a skill uses Default access
 * (``inherit.policy``, when known, is the level it stands for). */
export function useInstallationPolicyCopy() {
  const t = useTranslations("skills.installationPolicy");
  return {
    label: (
      policy: SkillInstallationPolicy | null,
      inherit: InheritOption = { scope: "skill", policy: null }
    ) => {
      if (policy !== null) return t(`${policy}.label`);
      if (inherit.policy === null)
        return t("inherit.label", { scope: inherit.scope });
      return t("inherit.labelWithPolicy", {
        scope: inherit.scope,
        policy: t(`${inherit.policy}.label`),
      });
    },
    description: (
      policy: SkillInstallationPolicy | null,
      scope: InheritOption["scope"] = "skill"
    ) =>
      policy === null
        ? t("inherit.description", { scope })
        : t(`${policy}.description`),
  };
}

interface PolicyOptionsConfig {
  levels?: readonly SkillInstallationPolicy[];
  inherit?: InheritOption;
}

/** The select options of an install setting, with an optional "no own
 * setting" option first. */
export function usePolicyOptions({
  levels = INSTALLATION_POLICIES,
  inherit,
}: PolicyOptionsConfig = {}): SelectOption[] {
  const copy = useInstallationPolicyCopy();
  const options: SelectOption[] = levels.map((policy) => ({
    value: policy,
    title: copy.label(policy),
    description: copy.description(policy),
  }));
  if (!inherit) return options;
  return [
    {
      value: INHERIT,
      title: copy.label(null, inherit),
      description: copy.description(null, inherit.scope),
    },
    ...options,
  ];
}
