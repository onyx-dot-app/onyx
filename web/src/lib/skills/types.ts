/**
 * Skills API response shapes; mirrors
 * `backend/onyx/server/features/skill/models.py`.
 */

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

export interface Skill {
  source: SkillSource;
  id: string;
  slug: string;
  name: string;
  description: string;

  is_available: boolean | null;
  unavailable_reason: string | null;

  is_public: boolean | null;
  /** True for private personal skills: not public, no direct/group shares. */
  is_personal: boolean;
  enabled: boolean | null;
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
  public_permission: SkillSharePermission | null;
  user_permission: SkillAccessLevel | null;
}

export type BuiltinSkill = Skill & {
  source: "builtin";
  is_available: boolean;
};

export type CustomSkill = Skill & {
  source: "custom";
  is_public: boolean;
  enabled: boolean;
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
}

export type SkillEditableDetail = CustomSkill & {
  instructions_markdown: string;
};
