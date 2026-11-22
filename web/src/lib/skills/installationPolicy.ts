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

/** What the "no own setting" option names: a group uses the Organization
 * setting, and a skill uses Default access. */
export interface InheritOption {
  scope: "group" | "skill";
  /** The level the option stands for; null when it is not known. */
  policy: SkillInstallationPolicy | null;
}
