"use client";

import { useMemo } from "react";
import { Section } from "@opal/layouts";
import ToolApprovalCard from "@/app/app/message/messageComponents/ToolApprovalCard";
import { getMultiModelLabel } from "@/app/app/message/multiModel";
import { useCurrentMessageTree } from "@/app/app/stores/useChatSessionStore";
import {
  readWaitingToolRequests,
  useToolRequestUi,
} from "@/lib/chat/toolApprovals";

interface ToolApprovalsRegionProps {
  /** Model name to provider slug, for the icons of multi-model answers. */
  modelProviderLookup: Map<string, string>;
  className?: string;
}

/**
 * Every approval card on the selected branch that waits for a decision, the
 * replies' and their background subagents', oldest first. It follows the last
 * message. A decided card shows its record here until the resolution
 * arrives; from then on the reply's timeline shows the record.
 */
export default function ToolApprovalsRegion({
  modelProviderLookup,
  className,
}: ToolApprovalsRegionProps) {
  const tree = useCurrentMessageTree();
  const localStatuses = useToolRequestUi((state) => state.localStatuses);
  const waiting = useMemo(
    () =>
      tree
        ? readWaitingToolRequests(tree).flatMap((item) =>
            item.kind === "approval" ? [item] : []
          )
        : [],
    [tree]
  );
  if (waiting.length === 0) return null;
  return (
    <div data-testid="tool-approvals-region" className={className}>
      <Section gap={0.75} alignItems="stretch" height="auto">
        {waiting.map(({ turnIndex, request, response, multiModel }) => (
          <ToolApprovalCard
            key={request.approval_id}
            approval={{
              turnIndex,
              request,
              status: localStatuses.get(request.approval_id) ?? "pending",
            }}
            model={
              multiModel
                ? getMultiModelLabel(response, modelProviderLookup)
                : undefined
            }
          />
        ))}
      </Section>
    </div>
  );
}
