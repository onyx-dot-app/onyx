import * as yup from "yup";

// Matches UserGroupSkills in ee/onyx/server/user_group/models.py.
const identifier = yup.string().uuid().defined();
const sharePermission = yup
  .string<"VIEWER" | "EDITOR">()
  .oneOf(["VIEWER", "EDITOR"])
  .defined();

export type GroupInstallationPolicy =
  | "AVAILABLE"
  | "DEFAULT"
  | "REQUIRED"
  | "NOT_AVAILABLE";

const installationPolicy = yup
  .string<GroupInstallationPolicy>()
  .oneOf(["AVAILABLE", "DEFAULT", "REQUIRED", "NOT_AVAILABLE"])
  .defined();

const settingFields = {
  permission: sharePermission,
  company_installation_policy: installationPolicy,
  // null inherits company_installation_policy.
  group_installation_policy: installationPolicy.nullable(),
  effective_installation_policy: installationPolicy,
  // A hint for the UI; the server decides each change.
  can_edit: yup.boolean().defined(),
};

export const groupMarketplaceSettingSchema = yup
  .object({
    marketplace_id: identifier,
    name: yup.string().defined(),
    following_skill_count: yup.number().integer().defined(),
    ...settingFields,
  })
  .defined();

export const groupSkillSettingSchema = yup
  .object({
    skill_id: identifier,
    name: yup.string().defined(),
    description: yup.string().defined(),
    source: yup
      .string<
        "UPLOADED" | "BUILT_IN" | "PERSONAL_MARKETPLACE" | "COMPANY_MARKETPLACE"
      >()
      .oneOf([
        "UPLOADED",
        "BUILT_IN",
        "PERSONAL_MARKETPLACE",
        "COMPANY_MARKETPLACE",
      ])
      .defined(),
    marketplace_id: identifier.nullable(),
    marketplace_name: yup.string().nullable().defined(),
    ...settingFields,
  })
  .defined();

export const userGroupSkillsSchema = yup
  .object({
    marketplaces: yup.array(groupMarketplaceSettingSchema).defined(),
    skills: yup.array(groupSkillSettingSchema).defined(),
  })
  .defined();

export type GroupMarketplaceSetting = yup.InferType<
  typeof groupMarketplaceSettingSchema
>;
export type GroupSkillSetting = yup.InferType<typeof groupSkillSettingSchema>;
export type UserGroupSkills = yup.InferType<typeof userGroupSkillsSchema>;

export type GroupSkillTarget =
  | { kind: "skill"; id: string }
  | { kind: "marketplace"; id: string };
