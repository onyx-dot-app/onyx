import type {
  UserGroupInfo,
  UserRow,
} from "@/refresh-pages/admin/UsersPage/interfaces";

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

export interface TokenRateLimitDisplay {
  token_id: number;
  enabled: boolean;
  token_budget: number;
  period_hours: number;
}

/** Mirrors backend PermissionRegistryEntry from onyx.auth.permissions. */
export interface PermissionRegistryEntry {
  id: string;
  display_name: string;
  description: string;
  permissions: string[];
  group: number;
}
