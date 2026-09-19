"use client";

import ApprovalCard from "@/app/craft/components/approvals/ApprovalCard";
import { useLiveApprovals } from "@/app/craft/hooks/useLiveApprovals";

interface LiveApprovalsRegionProps {
  sessionId: string | null;
}

// Renders one ApprovalCard per row returned by /live (already filtered
// to undecided + within wait window). No outer logo/wrapper — caller is
// responsible for placing this inside the previous assistant message
// region so cards visually attach to the agent's last turn.
//
// SWR cache invalidation is owned by useBuildStreaming's
// approval_requested handler and by ApprovalCard itself after a
// decision — this component just reads.
export default function LiveApprovalsRegion({
  sessionId,
}: LiveApprovalsRegionProps) {
  const { data } = useLiveApprovals(sessionId);

  if (!sessionId || !data || data.items.length === 0) {
    return null;
  }

  const sorted = [...data.items].sort(
    (a, b) => Date.parse(a.created_at) - Date.parse(b.created_at)
  );

  return (
    <div data-testid="live-approvals-region" className="flex flex-col gap-3">
      {sorted.map((approval) => (
        <ApprovalCard key={approval.approval_id} approval={approval} />
      ))}
    </div>
  );
}
