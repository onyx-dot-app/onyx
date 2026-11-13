"use client";

import { memo, useEffect, useRef, useState } from "react";
import { cn } from "@opal/utils";
import { FetchError } from "@/lib/fetcher";
import { postChatApprovalDecision } from "@/lib/chat/svc";
import type { ApprovalSubmitDecision } from "@/lib/approvals/types";
import {
  decidedStatus,
  type ToolApproval,
  useToolApprovalUi,
} from "@/lib/chat/toolApprovals";
import ApprovalCard from "@/sections/approvals/ApprovalCard";

interface ToolApprovalCardProps {
  approval: ToolApproval;
}

/** A chat tool call's approval request on the shared approval card. */
function ToolApprovalCard({ approval }: ToolApprovalCardProps) {
  const { request } = approval;
  const nudge = useToolApprovalUi((state) =>
    state.nudge?.approvalId === request.approval_id ? state.nudge.seq : null
  );
  const cardRef = useRef<HTMLDivElement>(null);
  const [shaking, setShaking] = useState(false);

  // A blocked send points the user at this card. Clearing the nudge keeps a
  // remounted card from repeating it.
  useEffect(() => {
    if (nudge === null) return;
    useToolApprovalUi.getState().clearNudge(nudge);
    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;
    cardRef.current?.scrollIntoView({
      behavior: reduceMotion ? "auto" : "smooth",
      block: "center",
    });
    // Restart a shake that is still running.
    setShaking(false);
    requestAnimationFrame(() => setShaking(true));
  }, [nudge]);

  // The decided status shows at once; the resolution packet then confirms it.
  async function submit(decision: ApprovalSubmitDecision) {
    const { recordStatus } = useToolApprovalUi.getState();
    try {
      recordStatus(
        request.approval_id,
        decidedStatus(
          await postChatApprovalDecision(request.approval_id, decision)
        )
      );
    } catch (cause) {
      // 409 or 404: the request no longer waits for a decision.
      if (
        !(cause instanceof FetchError) ||
        (cause.status !== 409 && cause.status !== 404)
      ) {
        throw cause;
      }
      recordStatus(request.approval_id, "closed");
    }
  }

  return (
    <div
      ref={cardRef}
      data-testid="tool-approval-card"
      className={cn(shaking && "motion-safe:animate-shake")}
      onAnimationEnd={(event) => {
        if (event.target === event.currentTarget) setShaking(false);
      }}
    >
      <ApprovalCard
        actions={[{ id: request.tool_name, name: request.display_name }]}
        payload={request.arguments}
        expiresAt={request.expires_at}
        sessionScope="chat"
        status={approval.status}
        onDecide={submit}
      />
    </div>
  );
}

// The hook rebuilds approvals on every streamed packet; the request object and
// status stay the same until something changes.
export default memo(
  ToolApprovalCard,
  (prev, next) =>
    prev.approval.request === next.approval.request &&
    prev.approval.status === next.approval.status
);
