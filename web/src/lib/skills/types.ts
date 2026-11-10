/**
 * Skills API response shapes; mirrors
 * `backend/onyx/server/features/skill/models.py`.
 */

import * as yup from "yup";

export type SkillInstallationPolicy =
  | "AVAILABLE"
  | "DEFAULT"
  | "REQUIRED"
  | "NOT_AVAILABLE";

export const SKILL_INSTALLATION_POLICIES: readonly SkillInstallationPolicy[] = [
  "AVAILABLE",
  "DEFAULT",
  "REQUIRED",
  "NOT_AVAILABLE",
];

export type SkillSource = "builtin" | "custom";
export type SkillAccessLevel = "OWNER" | "EDITOR" | "VIEWER";
export type SkillSharePermission = "EDITOR" | "VIEWER";

export interface SkillUserShare {
  user: {
    id: string;
    email: string;
  };
  permission: SkillSharePermission;
}

export interface SkillGroupShare {
  group_id: number;
  group_name: string;
  permission: SkillSharePermission;
  /** Omitted preserves the policy; null inherits the skill-wide policy. */
  installation_policy?: SkillInstallationPolicy | null;
}

/** Read-only group label. Filtered by the viewer's authority, so it is never
 * a full list of grants and never a replacement for `group_shares`. */
export interface SkillGroupSummary {
  group_id: number;
  group_name: string;
  /** Null inherits the skill-wide policy. */
  installation_policy: SkillInstallationPolicy | null;
  source: "direct" | "marketplace";
}

export interface SkillExternalAppDependency {
  external_app_id: number;
  name: string;
  enabled: boolean;
  ready: boolean;
}

export interface SkillMarketplace {
  id: string;
  name: string;
  personal: boolean;
  folder: string | null;
  follows_access: boolean;
  can_share: boolean;
}

export interface Skill {
  source: SkillSource;
  id: string;
  name: string;
  description: string;

  is_available: boolean | null;
  unavailable_reason: string | null;
  is_valid: boolean | null;

  /** True for private personal skills: not public, no direct/group shares. */
  is_personal: boolean;
  enabled: boolean;
  can_toggle: boolean;
  installation_policy: SkillInstallationPolicy;
  effective_installation_policy: SkillInstallationPolicy;
  author_user_id: string | null;
  author_email: string | null;
  owner: {
    id: string;
    email: string;
  } | null;
  ownership_vacant: boolean;
  created_at: string | null;
  updated_at: string | null;
  user_shares: SkillUserShare[];
  group_shares: SkillGroupShare[];
  group_summaries: SkillGroupSummary[];
  public_permission: SkillSharePermission | null;
  user_permission: SkillAccessLevel | null;
  external_app: SkillExternalAppDependency | null;
  marketplace: SkillMarketplace | null;
  retired_at: string | null;
  current_version_number: number | null;
}

export type BuiltinSkill = Skill & {
  source: "builtin";
  is_available: boolean;
};

export type CustomSkill = Skill & {
  source: "custom";
};

export interface SkillsList {
  builtins: Skill[];
  customs: Skill[];
}

export interface SkillPreview {
  source: SkillSource;
  id: string;
  name: string;
  description: string;
  author_email: string | null;
  instructions_markdown: string;
  external_app: SkillExternalAppDependency | null;
}

export type SkillEditableDetail = CustomSkill & {
  instructions_markdown: string;
  files: SkillBundleFile[];
};

export interface SkillBundleFile {
  path: string;
  size: number;
}

export interface SkillBundleContents {
  name: string;
  description: string;
  instructions_markdown: string;
  files: SkillBundleFile[];
}

export interface GitHubImportedSkill {
  skill: CustomSkill;
  disabled_reason: string | null;
}

export interface GitHubSkillNotImported {
  path: string;
  name: string;
  reason: string;
}

export interface GitHubSkillsImportResult {
  imported: GitHubImportedSkill[];
  not_imported: GitHubSkillNotImported[];
}

export const skillVersionSchema = yup.object({
  id: yup.string().defined(),
  version_number: yup.number().integer().min(1).defined(),
  created_at: yup.string().defined(),
  created_by: yup
    .object({
      id: yup.string().defined(),
      email: yup.string().defined(),
    })
    .nullable()
    .defined(),
  is_current: yup.boolean().defined(),
  has_bundle: yup.boolean().defined(),
  marketplace_revision: yup.string().nullable().defined(),
});

export type SkillVersion = yup.InferType<typeof skillVersionSchema>;
