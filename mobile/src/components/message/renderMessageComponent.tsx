/* eslint-disable react-hooks/static-components -- findRenderer returns a STABLE
   module-level renderer fn; rendering it as <Renderer/> is intentional dynamic
   dispatch (each renderer keeps its own hook scope), not a render-time factory. */
// renderMessageComponent.tsx — renderer dispatch. Mirrors web renderMessageComponent:
// ordered predicate routing (chat first; deep-research before generic tools) +
// RendererComponent (final-answer path) with mixed chat+image handling.

import { memo, type ReactNode } from "react";

import {
  CODE_INTERPRETER_TOOL_TYPES,
  PacketType,
  type Packet,
  type ChatPacket,
  type ImageGenerationToolPacket,
  type SearchToolStart,
  type StopReason,
  type ToolCallArgumentDelta,
} from "@/lib/types";
import {
  RenderType,
  type FullChatState,
  type MessageRenderer,
  type RendererOutput,
} from "@/components/message/interfaces";
import { isCodingAgentPackets } from "@/state/timeline/packetHelpers";

import { MessageTextRenderer } from "@/components/message/timeline/renderers/MessageTextRenderer";
import { ReasoningRenderer } from "@/components/message/timeline/renderers/ReasoningRenderer";
import { DeepResearchPlanRenderer } from "@/components/message/timeline/renderers/DeepResearchPlanRenderer";
import { ResearchAgentRenderer } from "@/components/message/timeline/renderers/ResearchAgentRenderer";
import { CodingAgentRenderer } from "@/components/message/timeline/renderers/CodingAgentRenderer";
import { GenericToolRenderer } from "@/components/message/timeline/renderers/GenericToolRenderer";
import { WebSearchToolRenderer } from "@/components/message/timeline/renderers/search/WebSearchToolRenderer";
import { InternalSearchToolRenderer } from "@/components/message/timeline/renderers/search/InternalSearchToolRenderer";
import { FetchToolRenderer } from "@/components/message/timeline/renderers/fetch/FetchToolRenderer";
import { FileReaderToolRenderer } from "@/components/message/timeline/renderers/filereader/FileReaderToolRenderer";
import { MemoryToolRenderer } from "@/components/message/timeline/renderers/memory/MemoryToolRenderer";
import { CustomToolRenderer } from "@/components/message/timeline/renderers/custom/CustomToolRenderer";
import { ImageToolRenderer } from "@/components/message/timeline/renderers/image/ImageToolRenderer";
import { PythonToolRenderer } from "@/components/message/timeline/renderers/code/PythonToolRenderer";

function isChatPacket(p: Packet): boolean {
  return (
    p.obj.type === PacketType.MESSAGE_START ||
    p.obj.type === PacketType.MESSAGE_DELTA ||
    p.obj.type === PacketType.MESSAGE_END
  );
}
function isWebSearchPacket(p: Packet): boolean {
  return (
    p.obj.type === PacketType.SEARCH_TOOL_START &&
    (p.obj as SearchToolStart).is_internet_search === true
  );
}
function isInternalSearchPacket(p: Packet): boolean {
  return (
    p.obj.type === PacketType.SEARCH_TOOL_START &&
    (p.obj as SearchToolStart).is_internet_search !== true
  );
}
function isImageToolPacket(p: Packet): boolean {
  return p.obj.type === PacketType.IMAGE_GENERATION_TOOL_START;
}
function isPythonToolPacket(p: Packet): boolean {
  return (
    p.obj.type === PacketType.PYTHON_TOOL_START ||
    (p.obj.type === PacketType.TOOL_CALL_ARGUMENT_DELTA &&
      (p.obj as ToolCallArgumentDelta).tool_type ===
        CODE_INTERPRETER_TOOL_TYPES.PYTHON)
  );
}
function isCustomToolPacket(p: Packet): boolean {
  return p.obj.type === PacketType.CUSTOM_TOOL_START;
}
function isFileReaderToolPacket(p: Packet): boolean {
  return p.obj.type === PacketType.FILE_READER_START;
}
function isFetchToolPacket(p: Packet): boolean {
  return p.obj.type === PacketType.FETCH_TOOL_START;
}
function isMemoryToolPacket(p: Packet): boolean {
  return (
    p.obj.type === PacketType.MEMORY_TOOL_START ||
    p.obj.type === PacketType.MEMORY_TOOL_NO_ACCESS
  );
}
function isReasoningPacket(p: Packet): boolean {
  return (
    p.obj.type === PacketType.REASONING_START ||
    p.obj.type === PacketType.REASONING_DELTA ||
    p.obj.type === PacketType.SECTION_END ||
    p.obj.type === PacketType.ERROR
  );
}
function isDeepResearchPlanPacket(p: Packet): boolean {
  return (
    p.obj.type === PacketType.DEEP_RESEARCH_PLAN_START ||
    p.obj.type === PacketType.DEEP_RESEARCH_PLAN_DELTA
  );
}
function isResearchAgentPacket(p: Packet): boolean {
  return (
    p.obj.type === PacketType.RESEARCH_AGENT_START ||
    p.obj.type === PacketType.INTERMEDIATE_REPORT_START ||
    p.obj.type === PacketType.INTERMEDIATE_REPORT_DELTA ||
    p.obj.type === PacketType.INTERMEDIATE_REPORT_CITED_DOCS
  );
}

export function findRenderer(packets: Packet[]): MessageRenderer<any> | null {
  if (packets.some(isChatPacket)) return MessageTextRenderer as MessageRenderer<any>;

  // Deep research has priority (groups can contain plan+reasoning+fetch).
  if (packets.some(isDeepResearchPlanPacket)) return DeepResearchPlanRenderer as MessageRenderer<any>;
  if (packets.some(isResearchAgentPacket)) return ResearchAgentRenderer as MessageRenderer<any>;
  if (isCodingAgentPackets(packets)) return CodingAgentRenderer as MessageRenderer<any>;

  if (packets.some(isWebSearchPacket)) return WebSearchToolRenderer as MessageRenderer<any>;
  if (packets.some(isInternalSearchPacket)) return InternalSearchToolRenderer as MessageRenderer<any>;
  if (packets.some(isImageToolPacket)) return ImageToolRenderer as MessageRenderer<any>;
  if (packets.some(isPythonToolPacket)) return PythonToolRenderer as MessageRenderer<any>;
  if (packets.some(isFileReaderToolPacket)) return FileReaderToolRenderer as MessageRenderer<any>;
  if (packets.some(isCustomToolPacket)) return CustomToolRenderer as MessageRenderer<any>;
  if (packets.some(isFetchToolPacket)) return FetchToolRenderer as MessageRenderer<any>;
  if (packets.some(isMemoryToolPacket)) return MemoryToolRenderer as MessageRenderer<any>;
  if (packets.some(isReasoningPacket)) return ReasoningRenderer as MessageRenderer<any>;

  // Any other tool packet -> labeled generic step (never blank).
  return GenericToolRenderer as MessageRenderer<any>;
}

export interface RendererComponentProps {
  packets: Packet[];
  chatState: FullChatState;
  messageNodeId?: number;
  hasTimelineThinking?: boolean;
  onComplete: () => void;
  animate: boolean;
  stopPacketSeen: boolean;
  stopReason?: StopReason;
  children: (result: RendererOutput) => ReactNode;
}

function areRendererPropsEqual(
  prev: RendererComponentProps,
  next: RendererComponentProps
): boolean {
  return (
    prev.packets === next.packets &&
    prev.stopPacketSeen === next.stopPacketSeen &&
    prev.stopReason === next.stopReason &&
    prev.animate === next.animate &&
    prev.chatState.agent?.id === next.chatState.agent?.id &&
    prev.chatState.docs === next.chatState.docs &&
    prev.chatState.citations === next.chatState.citations &&
    prev.messageNodeId === next.messageNodeId
  );
}

function NOOP() {}

// Display group with BOTH chat text and image packets: render text then images.
function MixedContentHandler({
  chatPackets,
  imagePackets,
  chatState,
  messageNodeId,
  hasTimelineThinking,
  onComplete,
  animate,
  stopPacketSeen,
  stopReason,
  children,
}: {
  chatPackets: Packet[];
  imagePackets: Packet[];
  chatState: FullChatState;
  messageNodeId?: number;
  hasTimelineThinking?: boolean;
  onComplete: () => void;
  animate: boolean;
  stopPacketSeen: boolean;
  stopReason?: StopReason;
  children: (result: RendererOutput) => ReactNode;
}) {
  return (
    <MessageTextRenderer
      packets={chatPackets as ChatPacket[]}
      state={chatState}
      messageNodeId={messageNodeId}
      hasTimelineThinking={hasTimelineThinking}
      onComplete={NOOP}
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

export const RendererComponent = memo(function RendererComponent({
  packets,
  chatState,
  messageNodeId,
  hasTimelineThinking,
  onComplete,
  animate,
  stopPacketSeen,
  stopReason,
  children,
}: RendererComponentProps) {
  const hasChat = packets.some(isChatPacket);
  const hasImage = packets.some(isImageToolPacket);

  if (hasChat && hasImage) {
    const shared = new Set<string>([PacketType.SECTION_END, PacketType.ERROR]);
    const chatPackets = packets.filter(
      (p) =>
        isChatPacket(p) ||
        p.obj.type === PacketType.CITATION_INFO ||
        shared.has(p.obj.type as string)
    );
    const imagePackets = packets.filter(
      (p) =>
        isImageToolPacket(p) ||
        p.obj.type === PacketType.IMAGE_GENERATION_TOOL_DELTA ||
        shared.has(p.obj.type as string)
    );
    return (
      <MixedContentHandler
        chatPackets={chatPackets}
        imagePackets={imagePackets}
        chatState={chatState}
        messageNodeId={messageNodeId}
        hasTimelineThinking={hasTimelineThinking}
        onComplete={onComplete}
        animate={animate}
        stopPacketSeen={stopPacketSeen}
        stopReason={stopReason}
      >
        {children}
      </MixedContentHandler>
    );
  }

  const Renderer = findRenderer(packets);
  if (!Renderer) {
    return children([{ icon: null, status: null, content: null }]);
  }

  // Render as a COMPONENT (JSX) so the renderer's hooks live in their own fiber.
  return (
    <Renderer
      packets={packets}
      state={chatState}
      messageNodeId={messageNodeId}
      hasTimelineThinking={hasTimelineThinking}
      onComplete={onComplete}
      animate={animate}
      renderType={RenderType.FULL}
      stopPacketSeen={stopPacketSeen}
      stopReason={stopReason}
    >
      {(results) => children(results)}
    </Renderer>
  );
}, areRendererPropsEqual);
