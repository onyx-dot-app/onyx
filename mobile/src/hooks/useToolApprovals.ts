import { useEffect, useMemo } from "react";
import { useShallow } from "zustand/react/shallow";

import { Packet } from "@/chat/streamingModels";
import {
  readToolApprovals,
  ToolApproval,
  toolApprovalStatus,
  useToolApprovalUi,
} from "@/chat/toolApprovals";

// The approval requests of one response, each with its status.
export function useToolApprovals(packets: Packet[]): ToolApproval[] {
  // Streams append to the same array, so its length keys the result too.
  const packetCount = packets.length;
  const { entries, stopped } = useMemo(
    () => readToolApprovals(packets.slice(0, packetCount)),
    [packets, packetCount],
  );
  // Only this response's statuses, so other decisions do not re-render it.
  const localStatuses = useToolApprovalUi(
    useShallow((state) =>
      entries.map((entry) =>
        state.localStatuses.get(entry.request.approval_id),
      ),
    ),
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
    [entries, localStatuses, stopped],
  );
}
