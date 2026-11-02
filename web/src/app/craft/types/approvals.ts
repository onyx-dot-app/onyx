import type { ActionPolicy } from "@/app/craft/v1/apps/registry";

export type ApprovalDecision = "APPROVED" | "REJECTED" | "EXPIRED";

export type ApprovalSubmitDecision =
  | "approve_once"
  | "approve_session"
  | "reject";

// Mirrors backend `ActionMatch`.
export interface ApprovalAction {
  action_type: string;
  display_name: string;
  description: string;
  policy: ActionPolicy;
}

export interface ApprovalView {
  approval_id: string;
  session_id: string;
  // Non-empty, sorted strictest-policy-first; actions[0] drove the gate.
  actions: ApprovalAction[];
  app_name: string;
  payload: Record<string, unknown>;
  display_payload: Record<string, unknown>;
  created_at: string;
  expires_at: string | null;
  can_approve_for_session?: boolean;
  decision: ApprovalDecision | null;
  decided_at: string | null;
  is_live: boolean;
}

export interface ApprovalListResponse {
  items: ApprovalView[];
}

export interface ApprovalStatusView {
  approval_id: string;
  decision: ApprovalDecision | null;
  is_live: boolean;
}
