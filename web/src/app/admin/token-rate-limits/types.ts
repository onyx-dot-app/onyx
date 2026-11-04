export enum Scope {
  USER = "user",
  USER_GROUP = "user_group",
  GLOBAL = "global",
}

export enum Period {
  DAILY = "DAILY",
  WEEKLY = "WEEKLY",
  MONTHLY = "MONTHLY",
}

export interface TokenRateLimitArgs {
  enabled: boolean;
  token_budget: number | null;
  period: Period;
  // Cents at the API boundary; the UI collects dollars and converts.
  cost_budget_cents?: number | null;
}

export interface TokenRateLimit {
  token_id: number;
  enabled: boolean;
  token_budget: number | null;
  period: Period;
  cost_budget_cents: number | null;
}

export interface TokenRateLimitDisplay extends TokenRateLimit {
  group_name?: string;
}
