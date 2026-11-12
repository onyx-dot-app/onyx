"use client";

import { useTranslations } from "next-intl";
import type { SelectOption } from "@opal/components";
import type { SkillInstallationPolicy } from "@/lib/skills/types";

/** The select value for "no own setting": a group follows the Organization
 * setting, and a skill follows Default access. */
export const INHERIT = "INHERIT";
export type PolicyChoice = SkillInstallationPolicy | typeof INHERIT;

/** Most open first, as Claude lists them. */
export const INSTALLATION_POLICIES: readonly SkillInstallationPolicy[] = [
  "REQUIRED",
  "DEFAULT",
  "AVAILABLE",
  "NOT_AVAILABLE",
];

export function isPolicyChoice(value: string): value is PolicyChoice {
  return (
    value === INHERIT ||
    INSTALLATION_POLICIES.some((policy) => policy === value)
  );
}

export function toPolicyChoice(
  policy: SkillInstallationPolicy | null
): PolicyChoice {
  return policy ?? INHERIT;
}

export function fromPolicyChoice(
  choice: PolicyChoice
): SkillInstallationPolicy | null {
  return choice === INHERIT ? null : choice;
}

/** The one set of level labels and help text. */
export function useInstallationPolicyCopy() {
  const t = useTranslations("skills.installationPolicy");
  return {
    label: (policy: SkillInstallationPolicy) => t(`${policy}.label`),
    description: (policy: SkillInstallationPolicy) =>
      t(`${policy}.description`),
  };
}

/** What the "no own setting" option names: a group uses the Organization
 * setting, and a skill uses Default access. */
export interface InheritOption {
  scope: "group" | "skill";
  /** The value the option stands for; null when it differs between skills. */
  policy: SkillInstallationPolicy | null;
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
  const t = useTranslations("skills.installationPolicy.inherit");
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
      title:
        inherit.policy === null
          ? t("label", { scope: inherit.scope })
          : t("labelWithPolicy", {
              scope: inherit.scope,
              policy: copy.label(inherit.policy),
            }),
      description: t("description", { scope: inherit.scope }),
    },
    ...options,
  ];
}
