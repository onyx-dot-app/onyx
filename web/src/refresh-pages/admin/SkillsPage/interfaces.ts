/**
 * Skills API response shapes — mirrors
 * `backend/onyx/server/features/skill/models.py`.
 *
 * V1 visibility model (admin-set only):
 * - `is_public = true`                              → org-wide
 * - `is_public = false` + non-empty `granted_group_ids` → group-scoped
 * - `is_public = false` + empty `granted_group_ids`     → private
 *
 * Direct user grants ("share with user X") are out of scope for V1; there is
 * no `skill__user` junction in the schema.
 */

export type SkillSource = "builtin" | "custom";

/**
 * UI-facing visibility tri-state. Mapped to/from `(is_public, granted_group_ids)`
 * by `visibilityFromSkill` / `visibilityToPatch` in `helpers.tsx`.
 */
export type SkillVisibility = "private" | "groups" | "org_wide";

export interface BuiltinSkill {
  source: "builtin";
  slug: string;
  name: string;
  description: string;
  is_available: boolean;
  unavailable_reason: string | null;
}

export interface CustomSkill {
  source: "custom";
  id: string;
  slug: string;
  name: string;
  description: string;
  is_public: boolean;
  enabled: boolean;
  author_user_id: string | null;
  author_email: string | null;
  created_at: string | null;
  updated_at: string | null;
  granted_group_ids: number[];
}

export interface SkillsList {
  builtins: BuiltinSkill[];
  customs: CustomSkill[];
}
