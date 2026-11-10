"use client";

import { useCallback, useMemo } from "react";
import { useFormatter, useTranslations } from "next-intl";
import useSWR, { type ScopedMutator } from "swr";
import { SvgEyeOff, SvgLock, SvgOrganization, SvgUser } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import { toast } from "@opal/layouts";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { useUser } from "@/providers/UserProvider";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  formatSkillSize,
  skillLimitUsersSchema,
  skillLimitViolationOf,
  skillUsageSummarySchema,
  type SkillLimitViolation,
} from "@/lib/skills/limits";
import { Permission } from "@/lib/types";
import { useSettings } from "@/lib/settings/hooks";
import type { SkillCardItem } from "@/sections/cards/SkillCard";
import { canDeleteSkill, canShareSkill } from "@/lib/skills/permissions";
import {
  SKILL_INSTALLATION_POLICIES,
  type SkillInstallationPolicy,
} from "@/lib/skills/types";

export interface InstallationPolicyOption {
  value: SkillInstallationPolicy;
  label: string;
  description: string;
  icon: IconFunctionComponent;
}

const POLICY_COPY = {
  AVAILABLE: { key: "available", icon: SvgUser },
  DEFAULT: { key: "default", icon: SvgOrganization },
  REQUIRED: { key: "required", icon: SvgLock },
  NOT_AVAILABLE: { key: "notAvailable", icon: SvgEyeOff },
} as const satisfies Record<
  SkillInstallationPolicy,
  { key: string; icon: IconFunctionComponent }
>;

/** Every installation policy, in display order, with its label. */
export function useInstallationPolicyOptions(): InstallationPolicyOption[] {
  const t = useTranslations("skills.modals.share.installation");
  return useMemo(
    () =>
      SKILL_INSTALLATION_POLICIES.map((value) => {
        const { key, icon } = POLICY_COPY[value];
        return {
          value,
          label: t(key),
          description: t(`${key}Description`),
          icon,
        };
      }),
    [t]
  );
}

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
    item.source === "custom" &&
    item.skill.effective_installation_policy === "REQUIRED";

  const authorTitle =
    item.source === "builtin" ? appName : item.author_email || appName;
  const dependency = item.external_app;
  const isDependencyUnavailable = dependency !== null && !dependency.ready;
  const isSelectedDependencyUnavailable =
    item.enabled && isDependencyUnavailable;
  const isInactive = !item.enabled || isDependencyUnavailable;
  const isInvalid = item.source === "custom" && item.skill.is_valid === false;
  const isBuiltinUnavailable = item.source === "builtin" && !item.is_available;
  const limitBlock = item.skill_limit_block ?? null;
  // Blocks exist only for app Skills: a toggle retries, others need a reconnect.
  const limitStatus =
    limitBlock && dependency
      ? item.can_toggle
        ? t("skill.limit.retry", { limit: limitBlock })
        : t("skill.limit.reconnect", {
            limit: limitBlock,
            app: dependency.name,
          })
      : null;
  let dependencyStatus: string | null = limitStatus;
  if (dependency && !limitStatus) {
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
  } else if (limitStatus) {
    tooltip = limitStatus;
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

async function fetchOwnSkillUsage(url: string) {
  return skillUsageSummarySchema.validateSync(
    await errorHandlingFetcher<unknown>(url),
    { strict: true }
  );
}

async function fetchSkillLimitUsers([url]: [string, string]) {
  return skillLimitUsersSchema.validateSync(
    await errorHandlingFetcher<unknown>(url),
    { strict: true }
  );
}

/** The signed-in user's Skill total against the write limit. */
export function useOwnSkillUsage(enabled = true) {
  const { data, error, isLoading, mutate } = useSWR(
    enabled ? SWR_KEYS.skillLimitMe : null,
    fetchOwnSkillUsage
  );
  return { usage: data, error, isLoading, refresh: mutate };
}

/**
 * Users past the write limit. Only global Skill managers may read it; the key
 * includes the user so another session never shows earlier rows.
 */
export function useSkillLimitUsers() {
  const { user } = useUser();
  const { isGlobalHolder } = usePermissionAuthority(Permission.MANAGE_SKILLS);
  const userId = user?.id ?? null;
  const allowed = isGlobalHolder && userId !== null;
  const { data, error, isLoading, mutate } = useSWR(
    isGlobalHolder && userId !== null
      ? [SWR_KEYS.skillLimitUsers, userId]
      : null,
    fetchSkillLimitUsers
  );
  return {
    allowed,
    users: allowed && !error ? data : undefined,
    error: allowed ? error : undefined,
    isLoading: allowed && isLoading,
    refresh: mutate,
  };
}

/** Revalidate cached Skill usage after a write. */
export async function revalidateSkillUsage(
  mutate: ScopedMutator
): Promise<void> {
  await mutate(
    (key) =>
      key === SWR_KEYS.skillLimitMe ||
      (Array.isArray(key) && key[0] === SWR_KEYS.skillLimitUsers)
  );
}

export interface SkillLimitFeedback {
  violation: SkillLimitViolation;
  title: string;
  description: string;
}

/**
 * Localized feedback for a Skill limit refusal: the requester's usage when
 * they go over, otherwise the number of affected users.
 */
export function useSkillLimitText(): (
  violation: SkillLimitViolation
) => SkillLimitFeedback {
  const t = useTranslations("skills.limit.refusal");
  const format = useFormatter();
  return useCallback(
    (violation: SkillLimitViolation) => {
      const title = t("title", { limit: violation.failed_limit });
      const { usage } = violation;
      if (!usage) {
        return {
          violation,
          title,
          description: t("affected", {
            limit: violation.failed_limit,
            count: violation.affected_user_count,
          }),
        };
      }
      const values = {
        size: formatSkillSize(format, usage.charged_bytes),
        files: usage.charged_files,
        maxSize: formatSkillSize(format, usage.max_bytes),
        maxFiles: usage.max_files,
        others: Math.max(violation.affected_user_count - 1, 0),
      };
      return {
        violation,
        title,
        description:
          usage.unknown_skill_count > 0
            ? t("ownEstimated", {
                ...values,
                unknown: usage.unknown_skill_count,
              })
            : t("own", values),
      };
    },
    [t, format]
  );
}

/** Feedback for a refused Skill write; null for every other error, so
 * callers keep their ordinary message. */
export function useSkillLimitFeedback(): (
  error: unknown
) => SkillLimitFeedback | null {
  const describe = useSkillLimitText();
  return useCallback(
    (error: unknown) => {
      const violation = skillLimitViolationOf(error);
      return violation ? describe(violation) : null;
    },
    [describe]
  );
}

/** Inline text for a failed Skill write: the limit explanation for a refusal,
 * otherwise the server detail, otherwise `fallback`. */
export function useSkillErrorMessage(): (
  error: unknown,
  fallback: string
) => string {
  const feedback = useSkillLimitFeedback();
  return useCallback(
    (error: unknown, fallback: string) =>
      feedback(error)?.description ??
      (error instanceof Error && error.message ? error.message : fallback),
    [feedback]
  );
}

/** Error toast for a failed Skill write; a limit refusal gets its own title. */
export function useSkillErrorToast(): (
  error: unknown,
  fallback: string
) => void {
  const feedback = useSkillLimitFeedback();
  return useCallback(
    (error: unknown, fallback: string) => {
      const limit = feedback(error);
      if (limit) {
        // Stays until dismissed so the usage figures can be read.
        toast.error(limit.title, {
          id: "skill-limit-refusal",
          description: limit.description,
          duration: Infinity,
        });
        return;
      }
      toast.error(
        error instanceof Error && error.message ? error.message : fallback
      );
    },
    [feedback]
  );
}
