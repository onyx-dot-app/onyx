export enum Period {
  DAILY = "DAILY",
  WEEKLY = "WEEKLY",
  MONTHLY = "MONTHLY",
}

export const PERIODS = [Period.DAILY, Period.WEEKLY, Period.MONTHLY];

export enum LimitAction {
  BLOCK = "BLOCK",
  ALERT_ONLY = "ALERT_ONLY",
}

/** One limit as the API returns it. Budgets: tokens in thousands, cost in cents. */
export interface SpendingLimit {
  id: number;
  period: Period;
  model_configuration_id: number | null;
  model_name: string | null;
  token_budget: number | null;
  cost_budget_cents: number | null;
  action: LimitAction;
  threshold_percent: number | null;
  reset_at: string;
  // Pool cards only.
  used_tokens: number | null;
  used_cost_cents: number | null;
}

export interface SpendingLimitCard {
  enabled: boolean;
  limits: SpendingLimit[];
}

export interface GroupSpendingLimitCards {
  pool: SpendingLimitCard;
  per_member: SpendingLimitCard;
}

export interface GroupSpendingLimits extends GroupSpendingLimitCards {
  user_group_id: number;
  group_name: string;
  member_count: number;
}

export interface SpendingLimitsResponse {
  workspace_pool: SpendingLimitCard;
  workspace_per_user: SpendingLimitCard;
  groups: GroupSpendingLimits[];
}

export interface SpendingLimitRequest {
  period: Period;
  model_configuration_id: number | null;
  token_budget: number | null;
  cost_budget_cents: number | null;
  action: LimitAction;
  threshold_percent: number | null;
}

export type CardPath =
  | "workspace/pool"
  | "workspace/per-user"
  | `groups/${number}/pool`
  | `groups/${number}/per-member`;
