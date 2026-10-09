// Priority-ordered renderer dispatch, mirroring web `renderMessageComponent`. First match wins.
//
// Only chat and reasoning are wired; the tool slots between them return null on purpose. Reasoning
// sits last and matches section_end/error, which in web are already claimed by whichever tool group
// they close — delete the intervening predicates and reasoning inherits every closed tool group,
// painting a search or image step as a bogus "Thinking" body. Adding a renderer swaps one `null`.
import {
  CODE_INTERPRETER_TOOL_TYPES,
  Packet,
  PacketType,
  ToolCallArgumentDelta,
} from "@/chat/streamingModels";
import {
  isCodingAgentPackets,
  isDeepResearchPlanPackets,
  isMemoryToolPackets,
} from "@/chat/timeline/packetHelpers";

import { MessageTextRenderer } from "./MessageTextRenderer";
import { ReasoningRenderer } from "./ReasoningRenderer";
import type { DispatchRenderer } from "./timelineContract";

function isChatPacket(packet: Packet): boolean {
  return (
    packet.obj.type === PacketType.MESSAGE_START ||
    packet.obj.type === PacketType.MESSAGE_DELTA ||
    packet.obj.type === PacketType.MESSAGE_END
  );
}

function isResearchAgentPacket(packet: Packet): boolean {
  return (
    packet.obj.type === PacketType.RESEARCH_AGENT_START ||
    packet.obj.type === PacketType.INTERMEDIATE_REPORT_START ||
    packet.obj.type === PacketType.INTERMEDIATE_REPORT_DELTA ||
    packet.obj.type === PacketType.INTERMEDIATE_REPORT_CITED_DOCS
  );
}

function isSearchToolPacket(packet: Packet): boolean {
  return packet.obj.type === PacketType.SEARCH_TOOL_START;
}

function isImageToolPacket(packet: Packet): boolean {
  return packet.obj.type === PacketType.IMAGE_GENERATION_TOOL_START;
}

function isPythonToolPacket(packet: Packet): boolean {
  return (
    packet.obj.type === PacketType.PYTHON_TOOL_START ||
    (packet.obj.type === PacketType.TOOL_CALL_ARGUMENT_DELTA &&
      (packet.obj as ToolCallArgumentDelta).tool_type ===
        CODE_INTERPRETER_TOOL_TYPES.PYTHON)
  );
}

function isFileReaderToolPacket(packet: Packet): boolean {
  return packet.obj.type === PacketType.FILE_READER_START;
}

function isCustomToolPacket(packet: Packet): boolean {
  return packet.obj.type === PacketType.CUSTOM_TOOL_START;
}

function isFetchToolPacket(packet: Packet): boolean {
  return packet.obj.type === PacketType.FETCH_TOOL_START;
}

function isReasoningPacket(packet: Packet): boolean {
  return (
    packet.obj.type === PacketType.REASONING_START ||
    packet.obj.type === PacketType.REASONING_DELTA ||
    packet.obj.type === PacketType.SECTION_END ||
    packet.obj.type === PacketType.ERROR
  );
}

export function findRenderer(packets: Packet[]): DispatchRenderer | null {
  if (packets.some(isChatPacket)) {
    return MessageTextRenderer;
  }

  // Deep research first: its groups can also carry reasoning/fetch packets.
  if (isDeepResearchPlanPackets(packets)) {
    return null; // PR 9x: deep-research plan
  }
  if (packets.some(isResearchAgentPacket)) {
    return null; // PR 9x: research agent
  }
  if (isCodingAgentPackets(packets)) {
    return null; // PR 9x: coding agent
  }

  // Web splits this on `is_internet_search`; both slots are unwired, so one predicate covers the pair.
  if (packets.some(isSearchToolPacket)) {
    return null; // PR 9x: web search / internal search
  }
  if (packets.some(isImageToolPacket)) {
    return null; // PR 9e: image generation
  }
  if (packets.some(isPythonToolPacket)) {
    return null; // PR 9x: python
  }
  if (packets.some(isFileReaderToolPacket)) {
    return null; // PR 9x: file reader
  }
  if (packets.some(isCustomToolPacket)) {
    return null; // PR 9x: custom tool
  }
  if (packets.some(isFetchToolPacket)) {
    return null; // PR 9x: fetch
  }
  if (isMemoryToolPackets(packets)) {
    return null; // PR 9x: memory
  }

  if (packets.some(isReasoningPacket)) {
    return ReasoningRenderer;
  }

  return null;
}
