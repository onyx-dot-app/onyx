// Reprocesses on each stream flush (the packet array's identity changes); cheap at chat scale.
import { useMemo } from "react";

import { Message } from "@/chat/interfaces";
import {
  ProcessedMessageState,
  createInitialState,
  processPackets,
} from "@/chat/messageProcessor";
import { Packet } from "@/chat/streamingModels";

export interface PacketDisplay {
  packets: Packet[];
  processed: ProcessedMessageState;
  // Drives the answer-vs-loader gate in MessageRow. Keyed on display groups, not on "some renderer
  // matches": a reasoning or tool group matches one too, but belongs above the answer, not in it.
  hasDisplayContent: boolean;
}

export function usePacketDisplay(node: Message): PacketDisplay {
  const processed = useMemo(
    () => processPackets(createInitialState(node.nodeId), node.packets),
    [node.nodeId, node.packets],
  );

  return {
    packets: node.packets,
    processed,
    hasDisplayContent: processed.potentialDisplayGroups.length > 0,
  };
}
