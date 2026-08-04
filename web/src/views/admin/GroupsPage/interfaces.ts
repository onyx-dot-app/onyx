import type { UserRole } from "@/lib/types";
import type { UserRow } from "@/views/admin/UsersPage/interfaces";

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

export interface TokenRateLimitDisplay {
  token_id: number;
  enabled: boolean;
  // null for a cost-only limit (matches the backend's nullable column).
  token_budget: number | null;
  period_hours: number;
  cost_budget_cents: number | null;
}
