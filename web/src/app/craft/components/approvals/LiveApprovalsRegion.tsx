"use client";

import { useEffect, useMemo } from "react";
import ApprovalCard from "@/app/craft/components/approvals/ApprovalCard";
import { useLiveApprovals } from "@/app/craft/hooks/useLiveApprovals";

interface LiveApprovalsRegionProps {
  sessionId: string | null;
  onApprovalCountChange?: (count: number) => void;
}

// Renders one ApprovalCard per row returned by /live (already filtered
// to undecided + within wait window). The region is intended for the
// pre-input stack and should stay above queued messages.
//
// SWR cache invalidation is owned by useBuildStreaming's
// approval_requested handler and by ApprovalCard itself after a
// decision — this component just reads.
export default function LiveApprovalsRegion({
  sessionId,
  onApprovalCountChange,
}: LiveApprovalsRegionProps) {
  const { data } = useLiveApprovals(sessionId);

  const sorted = useMemo(
    () =>
      data
        ? [...data.items].sort(
            (a, b) => Date.parse(a.created_at) - Date.parse(b.created_at)
          )
        : [],
    [data]
  );
  const approvalCount = sessionId ? sorted.length : 0;

  useEffect(() => {
    onApprovalCountChange?.(approvalCount);
  }, [approvalCount, onApprovalCountChange]);

  if (!sessionId || approvalCount === 0) return null;

  return (
    <div
      data-testid="live-approvals-region"
      className="flex flex-col gap-3 pb-1.5"
    >
      {sorted.map((approval) => (
        <ApprovalCard key={approval.approval_id} approval={approval} />
      ))}
    </div>
  );
}
