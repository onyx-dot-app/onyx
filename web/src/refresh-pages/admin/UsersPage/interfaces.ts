import type { UserRole, UserStatus } from "@/lib/types";

export interface UserGroupInfo {
  id: number;
  name: string;
}

export interface UserRow {
  id: string | null;
  email: string;
  role: UserRole | null;
  status: UserStatus;
  is_active: boolean;
  is_scim_synced: boolean;
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
