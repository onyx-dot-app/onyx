export type HookPoint = string;
export type HookFailStrategy = "hard" | "soft";

export interface HookPointMeta {
  hook_point: HookPoint;
  display_name: string;
  description: string;
  docs_url: string | null;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  default_timeout_seconds: number;
  default_fail_strategy: HookFailStrategy;
  fail_hard_description: string;
}

export interface HookResponse {
  id: number;
  name: string;
  hook_point: HookPoint;
  endpoint_url: string | null;
  /** Partially-masked API key (e.g. "abcd••••••••wxyz"), or null if no key is set. */
  api_key_masked: string | null;
  fail_strategy: HookFailStrategy;
  timeout_seconds: number;
  is_active: boolean;
  is_reachable: boolean | null;
  creator_email: string | null;
  created_at: string;
  updated_at: string;
}

export interface HookCreateRequest {
  name: string;
  hook_point: HookPoint;
  endpoint_url: string;
  api_key?: string;
  fail_strategy?: HookFailStrategy;
  timeout_seconds?: number;
}

export interface HookUpdateRequest {
  name?: string;
  endpoint_url?: string;
  api_key?: string | null;
  fail_strategy?: HookFailStrategy;
  timeout_seconds?: number;
}

export interface HookExecutionRecord {
  error_message: string | null;
  status_code: number | null;
  duration_ms: number | null;
  created_at: string;
}

export type HookValidateStatus =
  | "passed"
  | "auth_failed"
  | "timeout"
  | "cannot_connect";

export interface HookValidateResponse {
  status: HookValidateStatus;
  error_message: string | null;
}
