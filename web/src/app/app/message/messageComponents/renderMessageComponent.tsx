import React, { JSX, memo } from "react";
import {
  ChatPacket,
  isCodeInterpreterToolType,
  Packet,
  PacketType,
  ReasoningPacket,
  SearchToolStart,
  StopReason,
  ToolCallArgumentDelta,
} from "@/app/app/services/streamingModels";
import {
  FullChatState,
  MessageRenderer,
  RenderType,
  RendererOutput,
} from "@/app/app/message/messageComponents/types";
import { MessageTextRenderer } from "@/app/app/message/messageComponents/renderers/MessageTextRenderer";
import { ImageToolRenderer } from "@/app/app/message/messageComponents/renderers/ImageToolRenderer";
import { PythonToolRenderer } from "@/lib/timeline/chat/renderers/code/PythonToolRenderer";
import { CodingAgentRenderer } from "@/lib/timeline/chat/renderers/code/CodingAgentRenderer";
import {
  isCodingAgentPackets,
  NestedCall,
} from "@/lib/timeline/chat/packetHelpers";
import { ReasoningRenderer } from "@/lib/timeline/chat/renderers/reasoning/ReasoningRenderer";
import CustomToolRenderer from "@/app/app/message/messageComponents/renderers/CustomToolRenderer";
import { FileReaderToolRenderer } from "@/lib/timeline/chat/renderers/filereader/FileReaderToolRenderer";
import { FetchToolRenderer } from "@/lib/timeline/chat/renderers/fetch/FetchToolRenderer";
import { MemoryToolRenderer } from "@/lib/timeline/chat/renderers/memory/MemoryToolRenderer";
import { DeepResearchPlanRenderer } from "@/lib/timeline/chat/renderers/deepresearch/DeepResearchPlanRenderer";
import { ResearchAgentRenderer } from "@/lib/timeline/chat/renderers/deepresearch/ResearchAgentRenderer";
import { WebSearchToolRenderer } from "@/lib/timeline/chat/renderers/search/WebSearchToolRenderer";
import { InternalSearchToolRenderer } from "@/lib/timeline/chat/renderers/search/InternalSearchToolRenderer";

// Different types of chat packets using discriminated unions
interface GroupedPackets {
  packets: Packet[];
}

function isChatPacket(packet: Packet): packet is ChatPacket {
  return (
    packet.obj.type === PacketType.MESSAGE_START ||
    packet.obj.type === PacketType.MESSAGE_DELTA ||
    packet.obj.type === PacketType.MESSAGE_END
  );
}

function isWebSearchPacket(packet: Packet): boolean {
  if (packet.obj.type !== PacketType.SEARCH_TOOL_START) return false;
  return (packet.obj as SearchToolStart).is_internet_search === true;
}

function isInternalSearchPacket(packet: Packet): boolean {
  if (packet.obj.type !== PacketType.SEARCH_TOOL_START) return false;
  return (packet.obj as SearchToolStart).is_internet_search !== true;
}

function isImageToolPacket(packet: Packet) {
  return packet.obj.type === PacketType.IMAGE_GENERATION_TOOL_START;
}

function isPythonToolPacket(packet: Packet) {
  return (
    packet.obj.type === PacketType.PYTHON_TOOL_START ||
    (packet.obj.type === PacketType.TOOL_CALL_ARGUMENT_DELTA &&
      isCodeInterpreterToolType(
        (packet.obj as ToolCallArgumentDelta).tool_type
      ))
  );
}

function isCustomToolPacket(packet: Packet) {
  return packet.obj.type === PacketType.CUSTOM_TOOL_START;
}

function isFileReaderToolPacket(packet: Packet) {
  return packet.obj.type === PacketType.FILE_READER_START;
}

function isFetchToolPacket(packet: Packet) {
  return packet.obj.type === PacketType.FETCH_TOOL_START;
}

function isMemoryToolPacket(packet: Packet) {
  return (
    packet.obj.type === PacketType.MEMORY_TOOL_START ||
    packet.obj.type === PacketType.MEMORY_TOOL_NO_ACCESS
  );
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
  const { packets } = groupedPackets;

  if (packets.some(isChatPacket)) {
    return MessageTextRenderer;
  }
  // Deep research groups can also hold reasoning and fetch packets.
  if (packets.some(isDeepResearchPlanPacket)) {
    return DeepResearchPlanRenderer;
  }
  if (packets.some(isResearchAgentPacket)) {
    return ResearchAgentRenderer;
  }
  if (isCodingAgentPackets(packets)) {
    return CodingAgentRenderer;
  }
  if (packets.some(isWebSearchPacket)) {
    return WebSearchToolRenderer;
  }
  if (packets.some(isInternalSearchPacket)) {
    return InternalSearchToolRenderer;
  }
  if (packets.some(isImageToolPacket)) {
    return ImageToolRenderer;
  }
  if (packets.some(isPythonToolPacket)) {
    return PythonToolRenderer;
  }
  if (packets.some(isFileReaderToolPacket)) {
    return FileReaderToolRenderer;
  }
  if (packets.some(isCustomToolPacket)) {
    return CustomToolRenderer;
  }
  if (packets.some(isFetchToolPacket)) {
    return FetchToolRenderer;
  }
  if (packets.some(isMemoryToolPacket)) {
    return MemoryToolRenderer;
  }
  // SECTION_END and ERROR match here, so this check must stay last.
  if (packets.some(isReasoningPacket)) {
    return ReasoningRenderer;
  }
  return null;
}

// Props interface for RendererComponent
interface RendererComponentProps {
  packets: Packet[];
  nestedCalls: NestedCall[];
  streamPackets: Packet[];
  chatState: FullChatState;
  messageNodeId?: number;
  hasTimelineThinking?: boolean;
  onComplete: () => void;
  animate: boolean;
  restoredTextLength?: number;
  stopPacketSeen: boolean;
  stopReason?: StopReason;
  children: (result: RendererOutput) => JSX.Element;
}

// Custom comparison to prevent unnecessary re-renders
function areRendererPropsEqual(
  prev: RendererComponentProps,
  next: RendererComponentProps
): boolean {
  return (
    prev.packets === next.packets &&
    prev.nestedCalls === next.nestedCalls &&
    prev.streamPackets === next.streamPackets &&
    prev.stopPacketSeen === next.stopPacketSeen &&
    prev.stopReason === next.stopReason &&
    prev.animate === next.animate &&
    prev.restoredTextLength === next.restoredTextLength &&
    prev.chatState.agent?.id === next.chatState.agent?.id &&
    prev.messageNodeId === next.messageNodeId
    // Skip: onComplete, children (function refs), chatState (memoized upstream)
  );
}

// React component wrapper that directly uses renderer components
export const RendererComponent = memo(function RendererComponent({
  packets,
  nestedCalls,
  streamPackets,
  chatState,
  messageNodeId,
  hasTimelineThinking,
  onComplete,
  animate,
  restoredTextLength,
  stopPacketSeen,
  stopReason,
  children,
}: RendererComponentProps) {
  const RendererFn = findRenderer({ packets });

  if (!RendererFn) {
    return children([{ icon: null, status: null, content: <></> }]);
  }

  return (
    <RendererFn
      packets={packets}
      nestedCalls={nestedCalls}
      streamPackets={streamPackets}
      state={chatState}
      messageNodeId={messageNodeId}
      hasTimelineThinking={hasTimelineThinking}
      onComplete={onComplete}
      animate={animate}
      restoredTextLength={restoredTextLength}
      renderType={RenderType.FULL}
      stopPacketSeen={stopPacketSeen}
      stopReason={stopReason}
    >
      {(results: RendererOutput) => children(results)}
    </RendererFn>
  );
}, areRendererPropsEqual);
