// Derives a node's processed message state (citations, documents, completion) and whether any renderer
// matches its packets. Reprocesses on each stream flush (packet-array identity changes); cheap at chat
// scale.
import { useMemo } from "react";

import { Message } from "@/chat/interfaces";
import {
  ProcessedMessageState,
  createInitialState,
  processPackets,
} from "@/chat/messageProcessor";
import { Packet } from "@/chat/streamingModels";
import { findRenderer } from "@/components/chat/renderers/registry";

export interface PacketDisplay {
  packets: Packet[];
  processed: ProcessedMessageState;
  // Drives the answer-vs-loader gate in MessageRow.
  hasRenderer: boolean;
}

export function usePacketDisplay(node: Message): PacketDisplay {
  const processed = useMemo(
    () => processPackets(createInitialState(node.nodeId), node.packets),
    [node.nodeId, node.packets],
  );
  const hasRenderer = useMemo(
    () => findRenderer(node.packets) != null,
    [node.packets],
  );

  return { packets: node.packets, processed, hasRenderer };
}
