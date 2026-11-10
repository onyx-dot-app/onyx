import type {
  CustomSkill,
  SkillGroupShare,
  SkillInstallationPolicy,
} from "@/lib/skills/types";
import type { SkillShareUpdatePayload } from "@/lib/skills/api";

/** A group grant to save. `installation_policy` is sent only when present:
 * absent keeps the saved override, null clears it. */
export type SkillGroupShareDraft = Omit<
  SkillGroupShare,
  "installation_policy"
> & {
  installation_policy?: SkillInstallationPolicy | null;
};

export type SkillSharingDraft = Pick<
  CustomSkill,
  | "name"
  | "owner"
  | "ownership_vacant"
  | "user_permission"
  | "user_shares"
  | "public_permission"
  | "installation_policy"
> & {
  group_shares: SkillGroupShareDraft[];
  external_app: Pick<NonNullable<CustomSkill["external_app"]>, "name"> | null;
};

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
  canManageCompanySkills: boolean,
  { canEditPublicAccess = canManageCompanySkills } = {}
): SkillShareUpdatePayload {
  return {
    installation_policy: canManageCompanySkills
      ? draft.installation_policy
      : undefined,
    public_permission:
      !draft.external_app && canEditPublicAccess
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
      ...(share.installation_policy !== undefined && {
        installation_policy: share.installation_policy,
      }),
    })),
  };
}
