import {
  ChatPacket,
  Packet,
  PacketType,
  ToolPacket,
} from "../../services/streamingModels";
import { AnimationType, FullChatState, FullRenderer } from "./interfaces";
import { MessageTextFullRenderer } from "./renderers/MessageTextRenderer";
import { SearchToolFullRenderer } from "./renderers/SearchToolRenderer";
import { ImageToolFullRenderer } from "./renderers/ImageToolRenderer";
import { IconType } from "react-icons";

// Different types of chat packets using discriminated unions
export interface GroupedPackets {
  packets: Packet[];
}

function isChatPacket(packet: Packet): packet is ChatPacket {
  return (
    packet.obj.type === PacketType.MESSAGE_START ||
    packet.obj.type === PacketType.MESSAGE_DELTA ||
    packet.obj.type === PacketType.MESSAGE_END
  );
}

function isSearchToolPacket(packet: Packet): packet is ToolPacket {
  return (
    packet.obj.type === PacketType.TOOL_START &&
    packet.obj.tool_name === "search"
  );
}

function isImageToolPacket(packet: Packet): packet is ToolPacket {
  return (
    packet.obj.type === PacketType.TOOL_START &&
    packet.obj.tool_name === "image_generation"
  );
}

function findRenderer(
  groupedPackets: GroupedPackets,
  fullChatState: FullChatState
): FullRenderer<any, any> | null {
  if (groupedPackets.packets.some((packet) => isChatPacket(packet))) {
    return MessageTextFullRenderer;
  }
  if (groupedPackets.packets.some((packet) => isSearchToolPacket(packet))) {
    return SearchToolFullRenderer;
  }
  if (groupedPackets.packets.some((packet) => isImageToolPacket(packet))) {
    return ImageToolFullRenderer;
  }
  return null;
}

export function renderMessageComponent(
  groupedPackets: GroupedPackets,
  fullChatState: FullChatState,
  onComplete: () => void,
  animationType: AnimationType,
  useShortRenderer: boolean = false
): { icon: IconType | null; content: JSX.Element } {
  if (!groupedPackets.packets || !groupedPackets.packets[0]) {
    return { icon: null, content: <></> };
  }

  const renderer = findRenderer(groupedPackets, fullChatState);
  if (renderer) {
    return {
      icon: renderer.icon,
      content: useShortRenderer
        ? renderer.shortRenderer({
            packets: groupedPackets.packets,
            state: fullChatState,
            onComplete,
            animationType,
          })
        : renderer.extendedRenderer({
            packets: groupedPackets.packets,
            state: fullChatState,
            onComplete,
            animationType,
          }),
    };
  }

  return { icon: null, content: <></> };
}
