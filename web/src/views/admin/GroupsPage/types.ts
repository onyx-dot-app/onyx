import type { UserGroupInfo, UserRow } from "@/views/admin/UsersPage/types";

export interface ApiKeyDescriptor {
  api_key_id: number;
  api_key_display: string;
  api_key_name: string | null;
  groups: UserGroupInfo[];
  user_id: string;
}

/** Extends UserRow with an optional API key display for service accounts. */
export interface MemberRow extends UserRow {
  api_key_display?: string;
}

/** Mirrors backend PermissionRegistryEntry from onyx.auth.permissions. */
export interface PermissionRegistryEntry {
  id: string;
  display_name: string;
  description: string;
  permissions: string[];
  group: number;
  default_group_toggleable: boolean;
}
