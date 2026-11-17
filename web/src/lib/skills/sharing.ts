import type {
  CustomSkill,
  SkillGroupShare,
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

export function serializeSkillSharing(
  draft: SkillSharingDraft,
  isOrganizationManager: boolean
): SkillShareUpdatePayload {
  return {
    installation_policy: isOrganizationManager
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

/** A group's own setting, as the dialog edits it. The share of the group
 * comes from the share draft. */
export interface GroupSettingRow {
  group_id: number;
  group_name: string;
  choice: PolicyChoice;
}

/** One row of Group access: a group, its share and its setting. */
export interface GroupAccessRow extends GroupSettingRow {
  /** Null for a group with no share. */
  permission: SkillSharePermission | null;
}

/** The group settings to send: a changed row, a new row with a setting, and
 * null for a removed row that had one. */
export function groupSettingChanges(
  initial: readonly GroupSettingRow[],
  current: readonly GroupSettingRow[]
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

/** The rows of Group access: each setting with its share from the share
 * draft, then each shared group with no setting. A group with a share cannot
 * be Not available, so a share on such a group uses the Organization setting
 * (the save sends that); the stored choice is kept for an unstaged share. */
export function groupAccessRows(
  settings: readonly GroupSettingRow[],
  shares: readonly SkillGroupShare[]
): GroupAccessRow[] {
  const permissionOf = new Map(
    shares.map((share) => [share.group_id, share.permission])
  );
  const rows: GroupAccessRow[] = settings.map((row) => {
    const permission = permissionOf.get(row.group_id) ?? null;
    return {
      ...row,
      permission,
      choice:
        permission !== null && row.choice === "NOT_AVAILABLE"
          ? INHERIT
          : row.choice,
    };
  });
  const present = new Set(rows.map((row) => row.group_id));
  for (const share of shares) {
    if (present.has(share.group_id)) continue;
    rows.push({
      group_id: share.group_id,
      group_name: share.group_name,
      permission: share.permission,
      choice: INHERIT,
    });
  }
  return rows;
}
