export type ApprovalDecision = "APPROVED" | "REJECTED" | "EXPIRED";

// Decisions a client may submit. EXPIRED is server-only (the proxy
// writes it on timeout), so the union excludes it.
export type ApprovalSubmitDecision = "APPROVED" | "REJECTED";

export interface ApprovalView {
  approval_id: string;
  session_id: string;
  action_type: string;
  payload: Record<string, unknown>;
  created_at: string;
  decision: ApprovalDecision | null;
  decided_at: string | null;
  is_live: boolean;
}

export interface ApprovalListResponse {
  items: ApprovalView[];
}
