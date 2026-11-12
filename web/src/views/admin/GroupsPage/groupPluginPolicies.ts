"use client";

import { useTranslations } from "next-intl";
import type { SelectOption } from "@opal/components";
import type { SkillInstallationPolicy } from "@/lib/skills/types";

/** The select value for "no group setting". */
export const INHERIT = "INHERIT";
export type PolicyChoice = SkillInstallationPolicy | typeof INHERIT;

/** Most open first, as Claude lists them. */
export const GROUP_POLICIES: readonly SkillInstallationPolicy[] = [
  "REQUIRED",
  "DEFAULT",
  "AVAILABLE",
  "NOT_AVAILABLE",
];

export function isPolicyChoice(value: string): value is PolicyChoice {
  return value === INHERIT || GROUP_POLICIES.some((policy) => policy === value);
}

/** The setting options of a plugin. ``company`` is its organization setting;
 * pass null to leave out the "Organization setting" option. */
export function usePolicyOptions(company: SkillInstallationPolicy | null) {
  const t = useTranslations("admin.groups.plugins");

  function policyLabel(policy: SkillInstallationPolicy): string {
    return t(`policy.${policy}.label`);
  }

  const options: SelectOption[] = [
    ...(company === null
      ? []
      : [
          {
            value: INHERIT,
            title: t("option.inherit", { policy: policyLabel(company) }),
            description: t("option.inheritDescription"),
          },
        ]),
    ...GROUP_POLICIES.map((policy) => ({
      value: policy,
      title: policyLabel(policy),
      description: t(`policy.${policy}.description`),
    })),
  ];
  return { options, policyLabel };
}
