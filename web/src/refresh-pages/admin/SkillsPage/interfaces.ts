/**
 * Wireframe-only types for the Skills feature.
 * These mirror the shape described in `docs/craft/product/skills.md`
 * and are deliberately mock-grade (no backend bindings yet).
 */

export type SkillSource = "builtin" | "custom";

export type SkillVisibility =
  | "private"
  | "users"
  | "groups"
  | "users_and_groups"
  | "org_wide";

export type SkillFileKind =
  | "markdown"
  | "script"
  | "executable"
  | "binary"
  | "data";

export interface SkillBundleFile {
  path: string;
  size_bytes: number;
  executable: boolean;
  kind: SkillFileKind;
}

export interface SkillAuthor {
  id: string;
  name: string;
  email: string;
  is_admin: boolean;
}

export interface BuiltinSkill {
  slug: string;
  name: string;
  description: string;
  available: boolean;
  unavailable_reason?: string;
}

export interface CustomSkill {
  id: string;
  slug: string;
  name: string;
  description: string;
  author: SkillAuthor;
  visibility: SkillVisibility;
  shared_user_count: number;
  shared_group_count: number;
  enabled: boolean;
  promotion_requested: boolean;
  promoted_by_admin: boolean;
  admin_disabled_reason?: string;
  bundle: {
    sha256: string;
    total_bytes: number;
    files: SkillBundleFile[];
  };
  updated_at: string;
}

export interface SkillsForUser {
  owned: CustomSkill[];
  shared: CustomSkill[];
  builtin: BuiltinSkill[];
}
