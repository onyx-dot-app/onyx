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

export function serializeSkillSharing(
  draft: SkillSharingDraft,
  isAdmin: boolean
): SkillShareUpdatePayload {
  return {
    installation_policy: isAdmin ? draft.installation_policy : undefined,
    public_permission:
      !draft.external_app &&
      (draft.user_permission === "OWNER" ||
        (isAdmin && draft.user_permission === "EDITOR"))
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
