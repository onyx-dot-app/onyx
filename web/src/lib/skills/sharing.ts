import type {
  CustomSkill,
  SkillInstallationPolicy,
  SkillSharePermission,
} from "@/lib/skills/types";
import type {
  SkillGroupSettingPayload,
  SkillShareUpdatePayload,
} from "@/lib/skills/api";
import {
  INHERIT,
  fromPolicyChoice,
  type PolicyChoice,
} from "@/lib/skills/installationPolicy";

export type SkillSharingDraft = Pick<
  CustomSkill,
  | "name"
  | "owner"
  | "ownership_vacant"
  | "user_permission"
  | "user_shares"
  | "group_shares"
  | "public_permission"
  | "installation_policy"
> & {
  external_app: Pick<NonNullable<CustomSkill["external_app"]>, "name"> | null;
};

/** The author, or an organization-wide skill manager, changes organization
 * access: publish, and publish an update. An editor only saves versions. */
export function canChangeOrganizationAccess(
  skill: Pick<CustomSkill, "user_permission">,
  isOrganizationManager: boolean
): boolean {
  return (
    skill.user_permission === "OWNER" ||
    (isOrganizationManager && skill.user_permission === "EDITOR")
  );
}

/** A published skill whose current version the organization does not run. */
export function hasUnpublishedChanges(
  skill: Pick<
    CustomSkill,
    "current_version_number" | "published_version_number"
  >
): boolean {
  return (
    skill.published_version_number !== null &&
    skill.current_version_number !== null &&
    skill.current_version_number > skill.published_version_number
  );
}

export function emptySkillSharingDraft(
  name: string,
  owner: SkillSharingDraft["owner"]
): SkillSharingDraft {
  return {
    name,
    owner,
    ownership_vacant: false,
    user_permission: "OWNER",
    user_shares: [],
    group_shares: [],
    public_permission: null,
    installation_policy: null,
    external_app: null,
  };
}

/** ``initialPolicy`` is the company setting the dialog opened with. The
 * payload holds the setting only when it changed, so a save never turns "no
 * own setting" into an explicit value by accident. */
export function serializeSkillSharing(
  draft: SkillSharingDraft,
  isAdmin: boolean,
  isOrganizationManager: boolean,
  initialPolicy: SkillInstallationPolicy | null = null
): SkillShareUpdatePayload {
  return {
    installation_policy:
      isAdmin && draft.installation_policy !== initialPolicy
        ? draft.installation_policy
        : undefined,
    public_permission:
      !draft.external_app &&
      canChangeOrganizationAccess(draft, isOrganizationManager)
        ? draft.public_permission
        : undefined,
    user_shares: draft.user_shares
      .filter((share) => share.user.id !== draft.owner?.id)
      .map((share) => ({
        user_id: share.user.id,
        permission: share.permission,
      })),
    group_shares: draft.group_shares.map((share) => ({
      group_id: share.group_id,
      permission: share.permission,
    })),
  };
}

/** One row of the Group Access editor. */
export interface GroupAccessRow {
  group_id: number;
  group_name: string;
  /** Null for a group with no share. */
  permission: SkillSharePermission | null;
  choice: PolicyChoice;
}

/** The group settings to send: a changed row, a new row with a setting, and
 * null for a removed row that had one. */
export function groupSettingChanges(
  initial: readonly GroupAccessRow[],
  current: readonly GroupAccessRow[]
): SkillGroupSettingPayload[] {
  const before = new Map(initial.map((row) => [row.group_id, row.choice]));
  const changes: SkillGroupSettingPayload[] = current
    .filter((row) => row.choice !== (before.get(row.group_id) ?? INHERIT))
    .map((row) => ({
      group_id: row.group_id,
      installation_policy: fromPolicyChoice(row.choice),
    }));
  const kept = new Set(current.map((row) => row.group_id));
  for (const row of initial) {
    if (!kept.has(row.group_id) && row.choice !== INHERIT) {
      changes.push({ group_id: row.group_id, installation_policy: null });
    }
  }
  return changes;
}
