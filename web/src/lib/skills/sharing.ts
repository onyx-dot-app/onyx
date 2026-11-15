import type { CustomSkill } from "@/lib/skills/types";
import type { SkillShareUpdatePayload } from "@/lib/skills/api";

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
    installation_policy: "AVAILABLE",
    external_app: null,
  };
}

export function serializeSkillSharing(
  draft: SkillSharingDraft,
  isAdmin: boolean,
  isOrganizationManager: boolean
): SkillShareUpdatePayload {
  return {
    installation_policy: isAdmin ? draft.installation_policy : undefined,
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
