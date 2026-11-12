/**
 * Skills API response shapes; mirrors
 * `backend/onyx/server/features/skill/models.py`.
 */

export type SkillInstallationPolicy =
  | "AVAILABLE"
  | "DEFAULT"
  | "REQUIRED"
  | "NOT_AVAILABLE";

/** A marketplace default cannot be REQUIRED. */
export type OrganizationLibraryDefaultPolicy = Exclude<
  SkillInstallationPolicy,
  "REQUIRED"
>;

export interface OrganizationLibraryDefaultAccess {
  installation_policy: OrganizationLibraryDefaultPolicy;
}

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
}

/** One group row of a skill: a share, a group install setting, or both. */
export interface SkillGroupSummary {
  group_id: number;
  group_name: string;
  /** Null for a row that holds only a setting. */
  permission: SkillSharePermission | null;
  /** Null: the group uses the organization setting. */
  installation_policy: SkillInstallationPolicy | null;
}

export interface SkillExternalAppDependency {
  external_app_id: number;
  name: string;
  enabled: boolean;
  ready: boolean;
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
  /** The skill's own Organization setting. Null: Default access applies. */
  installation_policy: SkillInstallationPolicy | null;
  /** The Default access that applies when the skill has no own setting. */
  default_installation_policy: SkillInstallationPolicy | null;
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
  /** The group rows the caller may see; empty for other members. */
  group_summaries: SkillGroupSummary[];
  public_permission: SkillSharePermission | null;
  user_permission: SkillAccessLevel | null;
  external_app: SkillExternalAppDependency | null;
  /** Newest plugin version of a custom skill. Edits send it back as
   * `base_version_id`, so a save over a newer version gets a 409. */
  current_version_id: string | null;
  current_version_number: number | null;
  /** The version the organization runs. Null while the skill is private. */
  published_version_number: number | null;
  /** The version that waits for an admin's review. */
  pending_version_number: number | null;
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

export type SkillVersionReviewStatus =
  | "draft"
  | "pending"
  | "published"
  | "denied";

export interface SkillVersion {
  id: string;
  version_number: number;
  created_at: string;
  created_by_email: string | null;
  /** False when retention removed the files; the version cannot be restored. */
  bundle_kept: boolean;
  is_current: boolean;
  review_status: SkillVersionReviewStatus;
}

export interface SkillVersionPreview {
  version_number: number;
  description: string;
  instructions_markdown: string;
}

export interface SkillReviewRequest {
  skill_id: string;
  name: string | null;
  version_id: string;
  version_number: number;
  /** Null for a first publish. */
  published_version_number: number | null;
  requested_by_email: string | null;
  requested_at: string | null;
}

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

export interface GitHubSkillPreview {
  path: string;
  name: string;
  description: string | null;
  unavailable_reason: string | null;
}

export interface GitHubSkillsPreview {
  repository: string;
  revision: string;
  subpath: string | null;
  skills: GitHubSkillPreview[];
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
