import {
  ChatPacket,
  Packet,
  PacketType,
  ReasoningPacket,
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
import { ReasoningRenderer } from "./renderers/ReasoningRenderer";
import CustomToolRenderer from "./renderers/CustomToolRenderer";

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

function isSearchToolPacket(packet: Packet) {
  return packet.obj.type === PacketType.SEARCH_TOOL_START;
}

function isImageToolPacket(packet: Packet) {
  return packet.obj.type === PacketType.IMAGE_GENERATION_TOOL_START;
}

function isCustomToolPacket(packet: Packet) {
  return packet.obj.type === PacketType.CUSTOM_TOOL_START;
}

function isReasoningPacket(packet: Packet): packet is ReasoningPacket {
  return (
    packet.obj.type === PacketType.REASONING_START ||
    packet.obj.type === PacketType.REASONING_DELTA ||
    packet.obj.type === PacketType.SECTION_END
  );
}

export function findRenderer(
  groupedPackets: GroupedPackets
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
  if (groupedPackets.packets.some((packet) => isCustomToolPacket(packet))) {
    return CustomToolRenderer;
  }
  if (groupedPackets.packets.some((packet) => isReasoningPacket(packet))) {
    return ReasoningRenderer;
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

  const Renderer = findRenderer(groupedPackets);
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
