import type { AccountType, UserRole, UserStatus } from "@/lib/types";

export interface UserGroupInfo {
  id: number;
  name: string;
}

/** Backend response shape for user-management endpoints (`/manage/users*`). */
export interface FullUserSnapshot {
  id: string;
  email: string;
  role: UserRole;
  account_type: AccountType;
  is_active: boolean;
  password_configured: boolean;
  personal_name: string | null;
  created_at: string;
  updated_at: string;
  groups: UserGroupInfo[];
  is_scim_synced: boolean;
  /** Per-user Craft override; null = follow the workspace default. */
  craft_enabled: boolean | null;
}

export interface UserRow {
  id: string | null;
  email: string;
  role: UserRole | null;
  status: UserStatus;
  is_active: boolean;
  is_scim_synced: boolean;
  /** Per-user Craft override; null = follow the workspace default (also
   * null for rows that aren't real users: invited/requested, API keys). */
  craft_enabled: boolean | null;
  personal_name: string | null;
  created_at: string | null;
  updated_at: string | null;
  groups: UserGroupInfo[];
}

export interface GroupOption {
  id: number;
  name: string;
  memberCount?: number;
}

/** Empty array = no filter (show all). */
export type StatusFilter = UserStatus[];

/** Keys match the UserStatus-derived labels used in filter badges. */
export type StatusCountMap = {
  active?: number;
  inactive?: number;
  invited?: number;
  requested?: number;
};
