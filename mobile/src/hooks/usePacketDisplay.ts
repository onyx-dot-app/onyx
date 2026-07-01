// Groups a node's packets and picks a renderer. Core = one group; PR 9 adds real grouping.
import { useMemo } from "react";

import { Message } from "@/chat/interfaces";
import { Packet, PacketType } from "@/chat/streamingModels";
import {
  findRenderer,
  MessageRenderer,
} from "@/components/chat/renderers/registry";

export interface PacketDisplay {
  renderer: MessageRenderer | null;
  packets: Packet[];
  isComplete: boolean;
}

function isComplete(packets: Packet[]): boolean {
  return packets.some(
    (packet) =>
      packet.obj.type === PacketType.MESSAGE_END ||
      packet.obj.type === PacketType.STOP,
  );
}

export function usePacketDisplay(node: Message): PacketDisplay {
  // packets identity changes each flush, so this recomputes
  return useMemo(
    () => ({
      renderer: findRenderer(node.packets),
      packets: node.packets,
      isComplete: isComplete(node.packets),
    }),
    [node.packets],
  );
}
