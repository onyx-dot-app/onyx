import React from "react";
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
import { FetchToolRenderer } from "./renderers/FetchToolRenderer";

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

function isFetchToolPacket(packet: Packet) {
  return packet.obj.type === PacketType.FETCH_TOOL_START;
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
  if (groupedPackets.packets.some((packet) => isFetchToolPacket(packet))) {
    return FetchToolRenderer;
  }
  if (groupedPackets.packets.some((packet) => isReasoningPacket(packet))) {
    return ReasoningRenderer;
  }
  return null;
}

// React component wrapper that directly uses renderer components
export function RendererComponent({
  packets,
  chatState,
  onComplete,
  animate,
  stopPacketSeen,
  useShortRenderer = false,
  children,
}: {
  packets: Packet[];
  chatState: FullChatState;
  onComplete: () => void;
  animate: boolean;
  stopPacketSeen: boolean;
  useShortRenderer?: boolean;
  children: (result: RendererResult) => JSX.Element;
}) {
  const RendererFn = findRenderer({ packets });
  const renderType = useShortRenderer ? RenderType.HIGHLIGHT : RenderType.FULL;

  if (!RendererFn) {
    return children({ icon: null, status: null, content: <></> });
  }

  return (
    <RendererFn
      packets={packets as any}
      state={chatState}
      onComplete={onComplete}
      animate={animate}
      renderType={renderType}
      stopPacketSeen={stopPacketSeen}
    >
      {children}
    </RendererFn>
  );
}
