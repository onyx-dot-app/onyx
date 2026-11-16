import { apiFetch } from "@/api/client";
import type { ChatStream } from "@/chat/interfaces";
import type { ApprovalDecision } from "@/chat/toolApprovals";

export interface ApprovalDecisionResponse {
  approval_id: string;
  decision: "APPROVED" | "REJECTED";
  // "POLICY": the action policy disabled the tool, so the approval rejected it.
  decided_via: "USER" | "SESSION_GRANT" | "POLICY";
  // The stream that continues the suspended response, when this decision started or found it.
  continuation: ChatStream | null;
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
