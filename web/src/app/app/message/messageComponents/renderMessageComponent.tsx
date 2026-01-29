import React, { JSX } from "react";
import {
  ChatPacket,
  Packet,
  PacketType,
  ReasoningPacket,
  StopReason,
} from "../../services/streamingModels";
import {
  FullChatState,
  MessageRenderer,
  RenderType,
  RendererResult,
} from "./interfaces";
import { MessageTextRenderer } from "./renderers/MessageTextRenderer";
import { ImageToolRenderer } from "./renderers/ImageToolRenderer";
import { PythonToolRenderer } from "./renderers/PythonToolRenderer";
import { ReasoningRenderer } from "./renderers/ReasoningRenderer";
import CustomToolRenderer from "./renderers/CustomToolRenderer";
import { FetchToolRenderer } from "./renderers/FetchToolRenderer";
import { DeepResearchPlanRenderer } from "./renderers/DeepResearchPlanRenderer";
import { ResearchAgentRenderer } from "./renderers/ResearchAgentRenderer";
import { SearchToolRenderer } from "./renderers/SearchToolRenderer";

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

function isPythonToolPacket(packet: Packet) {
  return packet.obj.type === PacketType.PYTHON_TOOL_START;
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
    packet.obj.type === PacketType.SECTION_END ||
    packet.obj.type === PacketType.ERROR
  );
}

function isDeepResearchPlanPacket(packet: Packet) {
  return (
    packet.obj.type === PacketType.DEEP_RESEARCH_PLAN_START ||
    packet.obj.type === PacketType.DEEP_RESEARCH_PLAN_DELTA
  );
}

function isResearchAgentPacket(packet: Packet) {
  // Check for any packet type that indicates a research agent group
  return (
    packet.obj.type === PacketType.RESEARCH_AGENT_START ||
    packet.obj.type === PacketType.INTERMEDIATE_REPORT_START ||
    packet.obj.type === PacketType.INTERMEDIATE_REPORT_DELTA ||
    packet.obj.type === PacketType.INTERMEDIATE_REPORT_CITED_DOCS
  );
}

export function findRenderer(
  groupedPackets: GroupedPackets
): MessageRenderer<any, any> | null {
  // Check for chat messages first
  if (groupedPackets.packets.some((packet) => isChatPacket(packet))) {
    return MessageTextRenderer;
  }

  // Check for deep research packets EARLY - these have priority over other tools
  // because deep research groups may contain multiple packet types (plan + reasoning + fetch)
  if (
    groupedPackets.packets.some((packet) => isDeepResearchPlanPacket(packet))
  ) {
    return DeepResearchPlanRenderer;
  }
  if (groupedPackets.packets.some((packet) => isResearchAgentPacket(packet))) {
    return ResearchAgentRenderer;
  }

  // Standard tool checks
  if (groupedPackets.packets.some((packet) => isSearchToolPacket(packet))) {
    return SearchToolRenderer;
  }
  if (groupedPackets.packets.some((packet) => isImageToolPacket(packet))) {
    return ImageToolRenderer;
  }
  if (groupedPackets.packets.some((packet) => isPythonToolPacket(packet))) {
    return PythonToolRenderer;
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
  stopReason,
  useShortRenderer = false,
  children,
}: {
  packets: Packet[];
  chatState: FullChatState;
  onComplete: () => void;
  animate: boolean;
  stopPacketSeen: boolean;
  stopReason?: StopReason;
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
      stopReason={stopReason}
    >
      {children}
    </RendererFn>
  );
}
