import { useEffect, useMemo } from "react";
import { useShallow } from "zustand/react/shallow";
import type { Packet } from "@/app/app/services/streamingModels";
import type { GroupedPacket } from "@/app/app/message/messageComponents/timeline/hooks/packetProcessor";
import {
  readToolApprovals,
  type ToolApproval,
  toolApprovalStatus,
  useToolApprovalUi,
} from "@/lib/chat/toolApprovals";

/** The approval requests of one response, each with its final status. */
export function useToolApprovals(rawPackets: Packet[]): ToolApproval[] {
  // Streams append to the same array, so its length keys the result too.
  const packetCount = rawPackets.length;
  const { entries, stopped } = useMemo(
    () => readToolApprovals(rawPackets.slice(0, packetCount)),
    [rawPackets, packetCount]
  );
  // Only this response's statuses, so other decisions do not re-render it.
  const localStatuses = useToolApprovalUi(
    useShallow((state) =>
      entries.map((entry) => state.localStatuses.get(entry.request.approval_id))
    )
  );
  const resolvedIds = entries
    .filter((entry) => entry.outcome !== null)
    .map((entry) => entry.request.approval_id)
    .join(" ");
  useEffect(() => {
    if (resolvedIds)
      useToolApprovalUi.getState().forgetStatuses(resolvedIds.split(" "));
  }, [resolvedIds]);
  return useMemo(
    () =>
      entries.map((entry, index) => ({
        turnIndex: entry.turnIndex,
        request: entry.request,
        status: toolApprovalStatus(entry, localStatuses[index], stopped),
      })),
    [entries, localStatuses, stopped]
  );
}

export type SectionEntry =
  | { kind: "display"; turnIndex: number; group: GroupedPacket }
  | { kind: "approval"; turnIndex: number; approval: ToolApproval };

/**
 * Orders approval cards with a section's display groups by turn. A card
 * follows the display groups of its own turn and of every earlier turn.
 */
export function orderApprovalsByTurn(
  displayGroups: GroupedPacket[],
  approvals: ToolApproval[]
): SectionEntry[] {
  const entries: SectionEntry[] = displayGroups.map((group) => ({
    kind: "display",
    turnIndex: group.turn_index,
    group,
  }));
  for (const approval of approvals) {
    const index = entries.findIndex(
      (entry) => entry.turnIndex > approval.turnIndex
    );
    entries.splice(index === -1 ? entries.length : index, 0, {
      kind: "approval",
      turnIndex: approval.turnIndex,
      approval,
    });
  }
  return entries;
}
