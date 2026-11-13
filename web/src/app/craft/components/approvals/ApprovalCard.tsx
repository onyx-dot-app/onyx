"use client";

import { useState } from "react";
import { useSWRConfig } from "swr";

import {
  ApprovalConflictError,
  postApprovalDecision,
} from "@/app/craft/services/apiServices";
import { ApprovalDecision, ApprovalView } from "@/app/craft/types/approvals";
import type { ApprovalSubmitDecision } from "@/lib/approvals/types";
import SharedApprovalCard from "@/sections/approvals/ApprovalCard";
import { SWR_KEYS } from "@/lib/swr-keys";

interface ApprovalCardProps {
  approval: ApprovalView;
}

/** A Craft approval request on the shared approval card. */
export default function ApprovalCard({ approval }: ApprovalCardProps) {
  const { mutate } = useSWRConfig();
  const [decision, setDecision] = useState<ApprovalDecision | null>(
    approval.decision
  );
  const [approvedForSession, setApprovedForSession] = useState(false);
  const swrKey = SWR_KEYS.buildSessionApprovals(approval.session_id);

  async function submitDecision(choice: ApprovalSubmitDecision) {
    try {
      await postApprovalDecision(approval.approval_id, choice);
      setDecision(choice === "reject" ? "REJECTED" : "APPROVED");
      setApprovedForSession(choice === "approve_session");
    } catch (e) {
      // 409 = already resolved (by someone else, or expired by the proxy).
      // The refetch below shows the server outcome.
      if (!(e instanceof ApprovalConflictError)) throw e;
    }
    void mutate(swrKey);
  }

  return (
    <SharedApprovalCard
      actions={approval.actions.map((action) => ({
        id: action.action_type,
        name: action.display_name,
        description: action.description,
      }))}
      appName={approval.app_name}
      payload={approval.display_payload}
      expiresAt={approval.expires_at}
      canApproveForSession={approval.can_approve_for_session !== false}
      status={
        decision === "APPROVED"
          ? approvedForSession
            ? "approvedForSession"
            : "approved"
          : decision === "REJECTED"
            ? "rejected"
            : decision === "EXPIRED" || !approval.is_live
              ? "expired"
              : "pending"
      }
      onDecide={submitDecision}
    />
  );
}
