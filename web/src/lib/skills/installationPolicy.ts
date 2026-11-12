"use client";

import { useTranslations } from "next-intl";
import type { SelectOption } from "@opal/components";
import type { SkillInstallationPolicy } from "@/lib/skills/types";

/** The select value for "no own setting": a group follows the organization
 * setting, and a skill follows Default Access. */
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

function useLevelOptions(
  policies: readonly SkillInstallationPolicy[] = INSTALLATION_POLICIES
): SelectOption[] {
  const copy = useInstallationPolicyCopy();
  return policies.map((policy) => ({
    value: policy,
    title: copy.label(policy),
    description: copy.description(policy),
  }));
}

/** The settings of a group. ``company`` is the organization setting the
 * "no group setting" option names; undefined leaves the option out, and null
 * names no value (several skills at once). */
export function useGroupPolicyOptions(
  company: SkillInstallationPolicy | null | undefined
) {
  const t = useTranslations("skills.installationPolicy.inherit");
  const copy = useInstallationPolicyCopy();
  const levels = useLevelOptions();
  const options: SelectOption[] = [
    ...(company === undefined
      ? []
      : [
          {
            value: INHERIT,
            title:
              company === null
                ? t("groupAny")
                : t("group", { policy: copy.label(company) }),
            description: t("groupDescription"),
          },
        ]),
    ...levels,
  ];
  return { options, policyLabel: copy.label };
}

/** The company settings of a skill. ``defaultPolicy`` is the Default Access
 * that applies when the skill has no own setting; null names no value. */
export function useCompanyPolicyOptions(
  defaultPolicy: SkillInstallationPolicy | null
): SelectOption[] {
  const t = useTranslations("skills.installationPolicy.inherit");
  const copy = useInstallationPolicyCopy();
  const levels = useLevelOptions();
  return [
    {
      value: INHERIT,
      title:
        defaultPolicy === null
          ? t("organizationAny")
          : t("organization", { policy: copy.label(defaultPolicy) }),
      description: t("organizationDescription"),
    },
    ...levels,
  ];
}
