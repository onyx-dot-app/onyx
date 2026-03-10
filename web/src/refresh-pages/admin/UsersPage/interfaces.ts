import type { UserRole } from "@/lib/types";

export interface UserGroupInfo {
  id: number;
  name: string;
}

export interface UserRow {
  id: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  is_scim_synced: boolean;
  personal_name: string | null;
  created_at: string;
  updated_at: string;
  groups: UserGroupInfo[];
}

export type StatusFilter = "all" | "active" | "inactive";
