import { apiFetch } from "@/api/client";
import type { ApprovalDecision } from "@/chat/toolApprovals";

export interface ApprovalDecisionResponse {
  approval_id: string;
  decision: "APPROVED" | "REJECTED";
  // "POLICY": the action policy disabled the tool, so the approval rejected it.
  decided_via: "USER" | "SESSION_GRANT" | "POLICY";
}

// 404 or 409: the request no longer waits for a decision.
export function postApprovalDecision(
  approvalId: string,
  decision: ApprovalDecision,
): Promise<ApprovalDecisionResponse> {
  return apiFetch<ApprovalDecisionResponse>(
    `/chat/approvals/${encodeURIComponent(approvalId)}/decision`,
    { method: "POST", body: { decision } },
  );
}
