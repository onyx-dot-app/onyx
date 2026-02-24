import React, { JSX, memo } from "react";
import {
  ChatPacket,
  ImageGenerationToolPacket,
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
  RendererOutput,
} from "./interfaces";
import { MessageTextRenderer } from "./renderers/MessageTextRenderer";
import { ImageToolRenderer } from "./renderers/ImageToolRenderer";
import { PythonToolRenderer } from "./timeline/renderers/code/PythonToolRenderer";
import { ReasoningRenderer } from "./timeline/renderers/reasoning/ReasoningRenderer";
import CustomToolRenderer from "./renderers/CustomToolRenderer";
import { FileReaderToolRenderer } from "./timeline/renderers/filereader/FileReaderToolRenderer";
import { FetchToolRenderer } from "./timeline/renderers/fetch/FetchToolRenderer";
import { MemoryToolRenderer } from "./timeline/renderers/memory/MemoryToolRenderer";
import { DeepResearchPlanRenderer } from "./timeline/renderers/deepresearch/DeepResearchPlanRenderer";
import { ResearchAgentRenderer } from "./timeline/renderers/deepresearch/ResearchAgentRenderer";
import { WebSearchToolRenderer } from "./timeline/renderers/search/WebSearchToolRenderer";
import { InternalSearchToolRenderer } from "./timeline/renderers/search/InternalSearchToolRenderer";
import { SearchToolStart } from "../../services/streamingModels";

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
  return packet.obj.type === PacketType.PYTHON_TOOL_START;
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
  if (groupedPackets.packets.some((packet) => isWebSearchPacket(packet))) {
    return WebSearchToolRenderer;
  }
  if (groupedPackets.packets.some((packet) => isInternalSearchPacket(packet))) {
    return InternalSearchToolRenderer;
  }
  if (groupedPackets.packets.some((packet) => isImageToolPacket(packet))) {
    return ImageToolRenderer;
  }
  if (groupedPackets.packets.some((packet) => isPythonToolPacket(packet))) {
    return PythonToolRenderer;
  }
  if (groupedPackets.packets.some((packet) => isFileReaderToolPacket(packet))) {
    return FileReaderToolRenderer;
  }
  if (groupedPackets.packets.some((packet) => isCustomToolPacket(packet))) {
    return CustomToolRenderer;
  }
  if (groupedPackets.packets.some((packet) => isFetchToolPacket(packet))) {
    return FetchToolRenderer;
  }
  if (groupedPackets.packets.some((packet) => isMemoryToolPacket(packet))) {
    return MemoryToolRenderer;
  }
  if (groupedPackets.packets.some((packet) => isReasoningPacket(packet))) {
    return ReasoningRenderer;
  }
  return null;
}

// Handles display groups containing both chat text and image generation packets
function MixedContentHandler({
  chatPackets,
  imagePackets,
  chatState,
  onComplete,
  animate,
  stopPacketSeen,
  stopReason,
  children,
}: {
  chatPackets: Packet[];
  imagePackets: Packet[];
  chatState: FullChatState;
  onComplete: () => void;
  animate: boolean;
  stopPacketSeen: boolean;
  stopReason?: StopReason;
  children: (result: RendererOutput) => JSX.Element;
}) {
  return (
    <MessageTextRenderer
      packets={chatPackets as ChatPacket[]}
      state={chatState}
      onComplete={() => {}}
      animate={animate}
      renderType={RenderType.FULL}
      stopPacketSeen={stopPacketSeen}
      stopReason={stopReason}
    >
      {(textResults) => (
        <ImageToolRenderer
          packets={imagePackets as ImageGenerationToolPacket[]}
          state={chatState}
          onComplete={onComplete}
          animate={animate}
          renderType={RenderType.FULL}
          stopPacketSeen={stopPacketSeen}
          stopReason={stopReason}
        >
          {(imageResults) => children([...textResults, ...imageResults])}
        </ImageToolRenderer>
      )}
    </MessageTextRenderer>
  );
}

// Props interface for RendererComponent
interface RendererComponentProps {
  packets: Packet[];
  chatState: FullChatState;
  onComplete: () => void;
  animate: boolean;
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
    prev.stopPacketSeen === next.stopPacketSeen &&
    prev.stopReason === next.stopReason &&
    prev.animate === next.animate &&
    prev.chatState.assistant?.id === next.chatState.assistant?.id
    // Skip: onComplete, children (function refs), chatState (memoized upstream)
  );
}

// React component wrapper that directly uses renderer components
export const RendererComponent = memo(function RendererComponent({
  packets,
  chatState,
  onComplete,
  animate,
  stopPacketSeen,
  stopReason,
  children,
}: RendererComponentProps) {
  // Detect mixed display groups (both chat text and image generation)
  const hasChatPackets = packets.some((p) => isChatPacket(p));
  const hasImagePackets = packets.some((p) => isImageToolPacket(p));

  if (hasChatPackets && hasImagePackets) {
    const sharedTypes = new Set<string>([
      PacketType.SECTION_END,
      PacketType.ERROR,
    ]);

    const chatPackets = packets.filter(
      (p) =>
        isChatPacket(p) ||
        p.obj.type === PacketType.CITATION_INFO ||
        sharedTypes.has(p.obj.type as string)
    );
    const imagePackets = packets.filter(
      (p) =>
        isImageToolPacket(p) ||
        p.obj.type === PacketType.IMAGE_GENERATION_TOOL_DELTA ||
        sharedTypes.has(p.obj.type as string)
    );

    return (
      <MixedContentHandler
        chatPackets={chatPackets}
        imagePackets={imagePackets}
        chatState={chatState}
        onComplete={onComplete}
        animate={animate}
        stopPacketSeen={stopPacketSeen}
        stopReason={stopReason}
      >
        {children}
      </MixedContentHandler>
    );
  }

  const RendererFn = findRenderer({ packets });

  if (!RendererFn) {
    return children([{ icon: null, status: null, content: <></> }]);
  }

  return (
    <RendererFn
      packets={packets as any}
      state={chatState}
      onComplete={onComplete}
      animate={animate}
      renderType={RenderType.FULL}
      stopPacketSeen={stopPacketSeen}
      stopReason={stopReason}
    >
      {(results: RendererOutput) => children(results)}
    </RendererFn>
  );
}, areRendererPropsEqual);
