export enum Scope {
  USER = "user",
  USER_GROUP = "user_group",
  GLOBAL = "global",
}

export interface TokenRateLimitArgs {
  enabled: boolean;
  token_budget: number | null;
  period_hours: number;
  // Cents at the API boundary; the UI collects dollars and converts.
  cost_budget_cents?: number | null;
}

export interface TokenRateLimit {
  token_id: number;
  enabled: boolean;
  token_budget: number | null;
  period_hours: number;
  cost_budget_cents: number | null;
}

export interface TokenRateLimitDisplay extends TokenRateLimit {
  group_name?: string;
}
