import { useEffect, useMemo } from "react";
import { useShallow } from "zustand/react/shallow";

import { Packet } from "@/chat/streamingModels";
import type { ToolCardSpec } from "@/chat/toolCards";

// The cards of one kind in one response, each with its status.
export function useToolCards<Entry, Local, Card>(
  packets: Packet[],
  spec: ToolCardSpec<Entry, Local, Card>,
): Card[] {
  // Streams append to the same array, so its length keys the result too.
  const packetCount = packets.length;
  const entries = useMemo(
    () => spec.read(packets.slice(0, packetCount)),
    [packets, packetCount, spec],
  );
  // Only this response's statuses, so other cards' changes do not re-render it.
  const localStatuses = spec.useLocalStatuses(
    useShallow((state) =>
      entries.map((entry) => state.localStatuses.get(spec.id(entry))),
    ),
  );
  const resolvedIds = entries.filter(spec.resolved).map(spec.id).join(" ");
  useEffect(() => {
    if (resolvedIds) spec.forgetStatuses(resolvedIds.split(" "));
  }, [resolvedIds, spec]);
  return useMemo(
    () => entries.map((entry, index) => spec.card(entry, localStatuses[index])),
    [entries, localStatuses, spec],
  );
}
