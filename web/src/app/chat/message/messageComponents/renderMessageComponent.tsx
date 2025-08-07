import {
  ChatPacket,
  Packet,
  PacketType,
  ToolPacket,
} from "../../services/streamingModels";
import {
  FullChatState,
  MessageRenderer,
  RenderType,
  RendererResult,
} from "./interfaces";
import { MessageTextRenderer } from "./renderers/MessageTextRenderer";
import { SearchToolRenderer } from "./renderers/SearchToolRenderer";
import { ImageToolRenderer } from "./renderers/ImageToolRenderer";

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

export function findRenderer(
  groupedPackets: GroupedPackets,
  fullChatState: FullChatState
): MessageRenderer<any, any> | null {
  if (groupedPackets.packets.some((packet) => isChatPacket(packet))) {
    return MessageTextRenderer;
  }
  if (groupedPackets.packets.some((packet) => isSearchToolPacket(packet))) {
    return SearchToolRenderer;
  }
  if (groupedPackets.packets.some((packet) => isImageToolPacket(packet))) {
    return ImageToolRenderer;
  }
  return null;
}

export function renderMessageComponent(
  groupedPackets: GroupedPackets,
  fullChatState: FullChatState,
  onComplete: () => void,
  animate: boolean,
  useShortRenderer: boolean = false
): RendererResult {
  if (!groupedPackets.packets || !groupedPackets.packets[0]) {
    return { icon: null, status: null, content: <></> };
  }

  const Renderer = findRenderer(groupedPackets, fullChatState);
  if (Renderer) {
    const renderType = useShortRenderer
      ? RenderType.HIGHLIGHT
      : RenderType.FULL;

    return Renderer({
      packets: groupedPackets.packets,
      state: fullChatState,
      onComplete,
      renderType,
      animate,
    });
  }

  return { icon: null, status: null, content: <></> };
}
