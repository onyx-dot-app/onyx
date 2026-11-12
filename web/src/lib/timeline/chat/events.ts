/**
 * Turns chat stream packets into timeline events.
 *
 * Chat packets carry a placement (turn, tab, sub-turn). The timeline does not
 * use it for layout: it only builds stable ids from it, so live packets and
 * replayed history name the same tool calls and text parts. Tool events carry
 * the call's lifecycle and its Onyx tool type; the step body renders from the
 * tool's own packets.
 */

import {
  CODE_MODE_TOOL_TYPE,
  isCodeInterpreterToolType,
  PacketType,
  StopReason,
  type Packet,
} from "@/app/app/services/streamingModels";
import type { AcpToolKind, OnyxToolType } from "@/lib/timeline/acp";
import type { TimelineEvent } from "@/lib/timeline/events";

interface ToolStart {
  toolType: OnyxToolType;
  kind: AcpToolKind;
}

/** The packet that starts a tool step, or `null` for any other packet. */
function toolStart(packet: Packet): ToolStart | null {
  const { obj } = packet;
  switch (obj.type) {
    case PacketType.SEARCH_TOOL_START:
      return {
        toolType: obj.is_internet_search ? "web_search" : "internal_search",
        kind: "search",
      };
    case PacketType.FETCH_TOOL_START:
      return { toolType: "open_url", kind: "fetch" };
    case PacketType.PYTHON_TOOL_START:
      return { toolType: "python", kind: "execute" };
    case PacketType.TOOL_CALL_ARGUMENT_DELTA:
      // Streamed code arrives before the Python start packet.
      return isCodeInterpreterToolType(obj.tool_type)
        ? { toolType: "python", kind: "execute" }
        : null;
    case PacketType.IMAGE_GENERATION_TOOL_START:
      return { toolType: "image_generation", kind: "other" };
    case PacketType.CUSTOM_TOOL_START:
      return { toolType: "custom", kind: "other" };
    case PacketType.FILE_READER_START:
      return { toolType: "file_reader", kind: "read" };
    case PacketType.MEMORY_TOOL_START:
      return { toolType: "memory", kind: "edit" };
    case PacketType.DEEP_RESEARCH_PLAN_START:
      return { toolType: "deep_research_plan", kind: "think" };
    case PacketType.RESEARCH_AGENT_START:
      return { toolType: "research_agent", kind: "other" };
    case PacketType.CODING_AGENT_START:
      return { toolType: "coding_agent", kind: "execute" };
    case PacketType.BASH_TOOL_START:
      return { toolType: "bash", kind: "execute" };
    default:
      return null;
  }
}

/** A code mode program: its nested calls are the steps, not the program. */
function isCodeModeProgram(packet: Packet): boolean {
  const { obj } = packet;
  return (
    obj.type === PacketType.CODE_MODE_START ||
    obj.type === PacketType.CODE_MODE_DELTA ||
    (obj.type === PacketType.TOOL_CALL_ARGUMENT_DELTA &&
      obj.tool_type === CODE_MODE_TOOL_TYPE)
  );
}

function update(
  toolCallId: string,
  fields: { status?: "completed" | "failed"; cancelled?: true }
): TimelineEvent {
  return {
    type: "update",
    update: {
      sessionUpdate: "tool_call_update",
      toolCallId,
      ...(fields.status && { status: fields.status }),
      ...(fields.cancelled && { _meta: { onyx: { cancelled: true } } }),
    },
  };
}

export interface ChatEventAdapter {
  /** Returns the timeline events for the next packet of the message. */
  push(packet: Packet): TimelineEvent[];
}

/**
 * Creates an adapter for one assistant message. Packets must arrive in
 * stream order; create a new adapter when the message restarts.
 */
export function createChatEventAdapter(): ChatEventAdapter {
  /** Open tool calls: tool call id → turn index. */
  const open = new Map<string, number>();
  /** Every tool call started so far; a call starts once. */
  const started = new Set<string>();
  /** Sections whose packets belong to a code mode program. */
  const codeModeSections = new Set<string>();
  /** Sections whose nested calls belong to an agent's own page. */
  const agentSections = new Set<string>();
  let latestTurn = -1;

  /** A new turn ends every tool call still open from an earlier turn. */
  function closeEarlierTurns(turn: number): TimelineEvent[] {
    if (turn <= latestTurn) return [];
    latestTurn = turn;
    const events: TimelineEvent[] = [];
    for (const [id, callTurn] of open) {
      if (callTurn < turn) {
        events.push(update(id, { status: "completed" }));
        open.delete(id);
      }
    }
    return events;
  }

  function closeAll(fields: {
    status?: "completed";
    cancelled?: true;
  }): TimelineEvent[] {
    const events = Array.from(open.keys(), (id) => update(id, fields));
    open.clear();
    return events;
  }

  function push(packet: Packet): TimelineEvent[] {
    const { placement, obj } = packet;

    if (obj.type === PacketType.STOP) {
      switch (obj.stop_reason) {
        case StopReason.USER_CANCELLED:
          return [
            ...closeAll({ cancelled: true }),
            { type: "stop", stopReason: "cancelled" },
          ];
        case StopReason.TIMED_OUT:
          return [
            ...closeAll({ status: "completed" }),
            {
              type: "ext",
              notification: { method: "_onyx/timed_out", params: {} },
            },
          ];
        default:
          return [
            ...closeAll({ status: "completed" }),
            { type: "stop", stopReason: "end_turn" },
          ];
      }
    }

    const turn = placement.turn_index;
    const section = `${turn}-${placement.tab_index ?? 0}`;
    const sub = placement.sub_turn_index;
    const nested = sub !== undefined && sub !== null;
    const events = nested ? [] : closeEarlierTurns(turn);

    if (nested) {
      // An agent's nested calls belong on its own page. A code mode
      // program's nested calls are the timeline's steps.
      if (agentSections.has(section) || !codeModeSections.has(section)) {
        return events;
      }
    } else if (isCodeModeProgram(packet)) {
      codeModeSections.add(section);
      return events;
    }

    const key = nested ? `${section}/${sub}` : section;
    const toolCallId = `tc:${key}`;

    switch (obj.type) {
      case PacketType.MESSAGE_START:
      case PacketType.MESSAGE_DELTA: {
        if (nested || !obj.content) return events;
        return [
          ...events,
          {
            type: "update",
            update: {
              sessionUpdate: "agent_message_chunk",
              content: { type: "text", text: obj.content },
              _meta: { onyx: { partId: `msg:${key}` } },
            },
          },
        ];
      }
      case PacketType.REASONING_DELTA:
        return [
          ...events,
          {
            type: "update",
            update: {
              sessionUpdate: "agent_thought_chunk",
              content: { type: "text", text: obj.reasoning },
              _meta: { onyx: { partId: `think:${key}` } },
            },
          },
        ];
      case PacketType.SECTION_END:
        if (!open.has(toolCallId)) return events;
        open.delete(toolCallId);
        return [...events, update(toolCallId, { status: "completed" })];
      case PacketType.ERROR:
        if (!open.has(toolCallId)) return events;
        open.delete(toolCallId);
        return [...events, update(toolCallId, { status: "failed" })];
      default: {
        const start = toolStart(packet);
        if (!start || started.has(toolCallId)) return events;
        started.add(toolCallId);
        if (
          start.toolType === "research_agent" ||
          start.toolType === "coding_agent"
        ) {
          agentSections.add(section);
        }
        open.set(toolCallId, turn);
        return [
          ...events,
          {
            type: "update",
            update: {
              sessionUpdate: "tool_call",
              toolCallId,
              // The step's title comes from its tool type, in the UI's language.
              title: "",
              kind: start.kind,
              status: "in_progress",
              _meta: { onyx: { toolType: start.toolType } },
            },
          },
        ];
      }
    }
  }

  return { push };
}

/** Returns the timeline events for a whole message's packets. */
export function chatPacketsToEvents(
  packets: readonly Packet[]
): TimelineEvent[] {
  const adapter = createChatEventAdapter();
  return packets.flatMap((packet) => adapter.push(packet));
}
