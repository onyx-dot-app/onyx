// Picks a renderer for a node's packets and derives the processed message state (citations,
// documents, completion). A full pass over the node's packets runs whenever the array changes; the
// array's identity changes each stream flush, so this recomputes as packets arrive. Cheap at chat
// scale — the processor itself stays incremental-capable for 9b, which can host it differently.
import { useMemo } from "react";

import { Message } from "@/chat/interfaces";
import {
  ProcessedMessageState,
  createInitialState,
  processPackets,
} from "@/chat/messageProcessor";
import { Packet } from "@/chat/streamingModels";
import {
  findRenderer,
  MessageRenderer,
} from "@/components/chat/renderers/registry";

export interface PacketDisplay {
  renderer: MessageRenderer | null;
  packets: Packet[];
  processed: ProcessedMessageState;
}

export function usePacketDisplay(node: Message): PacketDisplay {
  const processed = useMemo(
    () => processPackets(createInitialState(node.nodeId), node.packets),
    [node.nodeId, node.packets],
  );
  const renderer = useMemo(() => findRenderer(node.packets), [node.packets]);

  return { renderer, packets: node.packets, processed };
}
