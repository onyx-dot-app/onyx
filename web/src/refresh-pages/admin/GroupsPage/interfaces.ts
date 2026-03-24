import type { UserRole } from "@/lib/types";
import type { UserRow } from "@/refresh-pages/admin/UsersPage/interfaces";

export interface ApiKeyDescriptor {
  api_key_id: number;
  api_key_display: string;
  api_key_name: string | null;
  api_key_role: UserRole;
  user_id: string;
}

/** Extends UserRow with an optional API key display for service accounts. */
export interface MemberRow extends UserRow {
  api_key_display?: string;
}
