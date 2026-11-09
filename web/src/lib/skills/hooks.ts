"use client";

import { useTranslations } from "next-intl";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import { useSettings } from "@/lib/settings/hooks";
import type { SkillCardItem } from "@/sections/cards/SkillCard";
import { canDeleteSkill, canShareSkill } from "@/lib/skills/permissions";

export function useSkillPresentation(
  item: SkillCardItem,
  hasEnabledNameConflict = false
) {
  const t = useTranslations("cards");
  const { appName } = useSettings();
  const { isGlobalHolder: canManageCompanySkills } = usePermissionAuthority(
    Permission.MANAGE_SKILLS
  );
  const isRequired =
    item.source === "custom" && item.skill.installation_policy === "REQUIRED";

  const authorTitle =
    item.source === "builtin" ? appName : item.author_email || appName;
  const dependency = item.external_app;
  const isDependencyUnavailable = dependency !== null && !dependency.ready;
  const isSelectedDependencyUnavailable =
    item.enabled && isDependencyUnavailable;
  const isInactive = !item.enabled || isDependencyUnavailable;
  const isInvalid = item.source === "custom" && item.skill.is_valid === false;
  const isBuiltinUnavailable = item.source === "builtin" && !item.is_available;
  let dependencyStatus: string | null = null;
  if (dependency) {
    if (!dependency.ready) {
      dependencyStatus = dependency.enabled
        ? item.enabled
          ? t("skill.dependency.connectToUse", { app: dependency.name })
          : t("skill.dependency.connectToEnable", { app: dependency.name })
        : t("skill.dependency.appDisabled", { app: dependency.name });
    } else {
      dependencyStatus =
        !item.enabled && hasEnabledNameConflict
          ? t("skill.dependency.nameConflict")
          : t("skill.dependency.usesApp", { app: dependency.name });
    }
  }

  let tooltip: string | undefined;
  if (isInvalid) {
    tooltip = t("skill.tooltips.invalid");
  } else if (isBuiltinUnavailable) {
    tooltip = t("skill.tooltips.unavailable");
  } else if (isDependencyUnavailable && dependency) {
    tooltip = dependency.enabled
      ? t("skill.tooltips.connectApp", { app: dependency.name })
      : t("skill.tooltips.appDisabled", { app: dependency.name });
  }
  const canEdit =
    item.source === "custom" &&
    !item.skill.retired_at &&
    (item.skill.user_permission === "OWNER" ||
      item.skill.user_permission === "EDITOR");

  const toggleAriaLabel = dependency
    ? item.enabled
      ? t("skill.toggle.disableForApp.ariaLabel", {
          name: item.name,
          app: dependency.name,
        })
      : t("skill.toggle.enableForApp.ariaLabel", {
          name: item.name,
          app: dependency.name,
        })
    : item.enabled
      ? t("skill.toggle.disable.ariaLabel", { name: item.name })
      : t("skill.toggle.enable.ariaLabel", { name: item.name });

  return {
    canManageCompanySkills,
    isRequired,
    authorTitle,
    dependency,
    isDependencyUnavailable,
    isSelectedDependencyUnavailable,
    isInactive,
    isInvalid,
    isBuiltinUnavailable,
    dependencyStatus,
    tooltip,
    canEdit,
    canShare: item.source === "custom" && canShareSkill({ skill: item.skill }),
    canDelete:
      item.source === "custom" &&
      canDeleteSkill({ skill: item.skill, canManageCompanySkills }),
    isSynced: item.source === "custom" && Boolean(item.skill.marketplace),
    toggleAriaLabel,
  };
}
