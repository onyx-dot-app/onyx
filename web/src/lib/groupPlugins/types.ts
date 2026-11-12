/**
 * Group plugins API shapes; mirrors `UserGroupPlugin` in
 * `backend/ee/onyx/server/user_group/models.py`.
 */

import type {
  SkillInstallationPolicy,
  SkillSharePermission,
} from "@/lib/skills/types";

export interface UserGroupPlugin {
  plugin_id: string;
  kind: "skill" | "plugin";
  /** A plugin of kind skill carries its skill name. */
  name: string;
  description: string;
  published: boolean;
  /** Null: the row holds only a group setting and gives no access. */
  permission: SkillSharePermission | null;
  /** Null: the group uses the organization setting. */
  installation_policy: SkillInstallationPolicy | null;
  company_installation_policy: SkillInstallationPolicy;
  can_edit: boolean;
}
