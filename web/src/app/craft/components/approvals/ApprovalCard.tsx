"use client";

import { useState } from "react";
import { useSWRConfig } from "swr";

import {
  ApprovalConflictError,
  postApprovalDecision,
} from "@/app/craft/services/apiServices";
import type { ApprovalView } from "@/app/craft/types/approvals";
import type {
  ApprovalStatus,
  ApprovalSubmitDecision,
} from "@/lib/approvals/types";
import SharedApprovalCard from "@/sections/approvals/ApprovalCard";
import { SWR_KEYS } from "@/lib/swr-keys";

interface ApprovalCardProps {
  approval: ApprovalView;
}

function approvalStatus(view: ApprovalView): ApprovalStatus {
  switch (view.decision) {
    case "APPROVED":
      return view.decided_via === "SESSION_GRANT"
        ? "approvedForSession"
        : "approved";
    case "REJECTED":
      return "rejected";
    case "EXPIRED":
      return "expired";
    case null:
      return view.is_live ? "pending" : "expired";
  }
}

/** A Craft approval request on the shared approval card. */
export default function ApprovalCard({ approval }: ApprovalCardProps) {
  const { mutate } = useSWRConfig();
  // The decision response shows the outcome until the list refetch lands.
  const [decided, setDecided] = useState<ApprovalView | null>(null);
  const swrKey = SWR_KEYS.buildSessionApprovals(approval.session_id);

  async function submitDecision(choice: ApprovalSubmitDecision) {
    try {
      setDecided(await postApprovalDecision(approval.approval_id, choice));
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
      status={approvalStatus(decided ?? approval)}
      onDecide={submitDecision}
    />
  );
}
