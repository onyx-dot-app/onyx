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
> &
  Partial<Pick<CustomSkill, "content_locked">>;

/** An owner or an editor manages a skill: shares it, edits it, deletes it. */
export function canManageSkill(
  skill: Pick<CustomSkill, "user_permission">
): boolean {
  return (
    skill.user_permission === "OWNER" || skill.user_permission === "EDITOR"
  );
}

/** An owner or an editor shares a skill. Only the owner of a personal GitHub
 * marketplace gets its plugins, so they are never shared. */
export function canShareSkill(
  skill: Pick<CustomSkill, "user_permission" | "marketplace">
): boolean {
  if (skill.marketplace?.personal) return false;
  return canManageSkill(skill);
}

/** The author, or an organization-wide skill manager, changes organization
 * access: publish, and publish an update. An editor only saves versions. A
 * skill synced from GitHub takes neither. */
export function canChangeOrganizationAccess(
  skill: Pick<CustomSkill, "user_permission"> &
    Partial<Pick<CustomSkill, "content_locked">>,
  isOrganizationManager: boolean
): boolean {
  if (skill.content_locked) return false;
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
  };
}

function userShareRequests(draft: SkillSharingDraft) {
  return draft.user_shares
    .filter((share) => share.user.id !== draft.owner?.id)
    .map((share) => ({
      user_id: share.user.id,
      permission: share.permission,
    }));
}

function groupShareRequests(draft: SkillSharingDraft) {
  return draft.group_shares.map((share) => ({
    group_id: share.group_id,
    permission: share.permission,
  }));
}

function sameShares<T extends { permission: string }>(
  a: T[],
  b: T[],
  key: (share: T) => string
): boolean {
  const byKey = new Map(b.map((share) => [key(share), share.permission]));
  return (
    a.length === b.length &&
    a.every((share) => byKey.get(key(share)) === share.permission)
  );
}

/** The access change to send. With `initial`, the access the dialog loaded,
 * a field the user did not change is left out, so the save keeps what
 * someone else changed in the meantime. */
export function serializeSkillSharing(
  draft: SkillSharingDraft,
  isOrganizationManager: boolean,
  initial?: SkillSharingDraft
): SkillShareUpdatePayload {
  const userShares = userShareRequests(draft);
  const groupShares = groupShareRequests(draft);
  const changed = <T>(value: T, unchanged: boolean): T | undefined =>
    initial && unchanged ? undefined : value;
  return {
    installation_policy: isOrganizationManager
      ? changed(
          draft.installation_policy,
          draft.installation_policy === initial?.installation_policy
        )
      : undefined,
    public_permission: canChangeOrganizationAccess(draft, isOrganizationManager)
      ? changed(
          draft.public_permission,
          draft.public_permission === initial?.public_permission
        )
      : undefined,
    user_shares: changed(
      userShares,
      !!initial &&
        sameShares(userShares, userShareRequests(initial), (s) => s.user_id)
    ),
    group_shares: changed(
      groupShares,
      !!initial &&
        sameShares(groupShares, groupShareRequests(initial), (s) =>
          String(s.group_id)
        )
    ),
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
