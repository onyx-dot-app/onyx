export enum Scope {
  USER = "user",
  USER_GROUP = "user_group",
  GLOBAL = "global",
}

export interface TokenRateLimitArgs {
  enabled: boolean;
  token_budget: number;
  period_hours: number;
}

export interface TokenRateLimit {
  token_id: number;
  enabled: boolean;
  token_budget: number;
  period_hours: number;
}

export interface TokenRateLimitDisplay extends TokenRateLimit {
  group_name?: string;
}
