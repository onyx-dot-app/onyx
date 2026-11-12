import type {
  AcpContentBlock,
  AcpMeta,
  AcpPlanEntry,
  AcpStopReason,
  AcpToolCallContent,
  AcpToolCallLocation,
  AcpToolCallProgress,
  AcpToolCallStart,
  AcpToolCallStatus,
  AcpToolKind,
} from "@/lib/timeline/acp";
import type { TimelineEvent } from "@/lib/timeline/events";
import type { TimelineEntry, TimelineEntryStatus } from "@/lib/timeline/types";

/** A tool call with every ACP field resolved. */
export interface AcpToolCall {
  toolCallId: string;
  title: string;
  kind: AcpToolKind | null;
  status: AcpToolCallStatus;
  content: AcpToolCallContent[];
  locations: AcpToolCallLocation[];
  rawInput: unknown;
  rawOutput: unknown;
  _meta: AcpMeta | null;
}

export type AcpTimelinePayload =
  | { kind: "thinking"; text: string }
  | { kind: "tool"; toolCall: AcpToolCall };

export type AcpTimelineEntry = TimelineEntry<AcpTimelinePayload>;

export interface TimelineState {
  /** Thinking blocks and tool calls, in arrival order. */
  entries: AcpTimelineEntry[];
  /** The agent's message. Adjacent text chunks are joined. */
  message: AcpContentBlock[];
  /** The latest plan. */
  plan: AcpPlanEntry[];
  /** Set when the turn ends. */
  stopReason: AcpStopReason | null;
  /** Set when the turn fails. */
  error: string | null;
}

export const INITIAL_TIMELINE_STATE: TimelineState = {
  entries: [],
  message: [],
  plan: [],
  stopReason: null,
  error: null,
};

function toolEntryStatus(toolCall: AcpToolCall): TimelineEntryStatus {
  if (toolCall._meta?.onyx?.cancelled) return "stopped";
  switch (toolCall.status) {
    case "failed":
      return "error";
    case "completed":
      return "done";
    case "pending":
    case "in_progress":
      return "streaming";
  }
}

function toolEntry(toolCall: AcpToolCall): AcpTimelineEntry {
  return {
    id: toolCall.toolCallId,
    status: toolEntryStatus(toolCall),
    // The timeline is linear: concurrent tool calls are separate entries.
    groupId: null,
    payload: { kind: "tool", toolCall },
  };
}

function mergeMeta(
  current: AcpMeta | null,
  next: AcpMeta | null | undefined
): AcpMeta | null {
  if (!next) return current;
  if (!current) return next;
  return { ...current, ...next, onyx: { ...current.onyx, ...next.onyx } };
}

/** Applies the fields an update sets; fields it leaves out keep their value. */
function applyToolUpdate(
  toolCall: AcpToolCall,
  update: AcpToolCallStart | AcpToolCallProgress
): AcpToolCall {
  return {
    toolCallId: toolCall.toolCallId,
    title: update.title ?? toolCall.title,
    kind: update.kind ?? toolCall.kind,
    status: update.status ?? toolCall.status,
    content: update.content ?? toolCall.content,
    locations: update.locations ?? toolCall.locations,
    rawInput:
      update.rawInput !== undefined ? update.rawInput : toolCall.rawInput,
    rawOutput:
      update.rawOutput !== undefined ? update.rawOutput : toolCall.rawOutput,
    _meta: mergeMeta(toolCall._meta, update._meta),
  };
}

function newToolCall(toolCallId: string): AcpToolCall {
  return {
    toolCallId,
    title: "",
    kind: null,
    status: "pending",
    content: [],
    locations: [],
    rawInput: undefined,
    rawOutput: undefined,
    _meta: null,
  };
}

/**
 * Starts or updates a tool call. An update for an unknown id adds the call,
 * because a client can attach to a stream after the call started.
 */
function upsertToolCall(
  entries: AcpTimelineEntry[],
  update: AcpToolCallStart | AcpToolCallProgress
): AcpTimelineEntry[] {
  const index = entries.findIndex((entry) => entry.id === update.toolCallId);
  const existing = entries[index];
  if (!existing || existing.payload.kind !== "tool") {
    return [
      ...entries,
      toolEntry(applyToolUpdate(newToolCall(update.toolCallId), update)),
    ];
  }
  const next = toolEntry(applyToolUpdate(existing.payload.toolCall, update));
  return entries.map((entry, i) => (i === index ? next : entry));
}

/** Ends the open thinking block, if the last entry is one. */
function settleThinking(entries: AcpTimelineEntry[]): AcpTimelineEntry[] {
  const last = entries[entries.length - 1];
  if (last?.payload.kind !== "thinking" || last.status !== "streaming") {
    return entries;
  }
  return [...entries.slice(0, -1), { ...last, status: "done" }];
}

function appendThought(
  entries: AcpTimelineEntry[],
  content: AcpContentBlock
): AcpTimelineEntry[] {
  // Thoughts are text; other block types carry nothing to show here.
  if (content.type !== "text") return entries;
  const last = entries[entries.length - 1];
  if (last?.payload.kind === "thinking" && last.status === "streaming") {
    const text = last.payload.text + content.text;
    return [
      ...entries.slice(0, -1),
      { ...last, payload: { kind: "thinking", text } },
    ];
  }
  return [
    ...entries,
    {
      id: `thinking-${entries.length}`,
      status: "streaming",
      groupId: null,
      payload: { kind: "thinking", text: content.text },
    },
  ];
}

function appendMessage(
  message: AcpContentBlock[],
  content: AcpContentBlock
): AcpContentBlock[] {
  const last = message[message.length - 1];
  if (last?.type === "text" && content.type === "text") {
    return [
      ...message.slice(0, -1),
      { ...last, text: last.text + content.text },
    ];
  }
  return [...message, content];
}

/** Applies one event. Pure: returns a new state and never mutates `state`. */
export function reduceTimeline(
  state: TimelineState,
  event: TimelineEvent
): TimelineState {
  if (event.type === "stop") {
    return {
      ...state,
      entries: settleThinking(state.entries),
      stopReason: event.stopReason,
    };
  }
  if (event.type === "error") {
    return {
      ...state,
      entries: settleThinking(state.entries),
      error: event.message,
    };
  }

  const { update } = event;
  switch (update.sessionUpdate) {
    case "agent_thought_chunk":
      return {
        ...state,
        entries: appendThought(state.entries, update.content),
      };
    case "agent_message_chunk":
      return {
        ...state,
        entries: settleThinking(state.entries),
        message: appendMessage(state.message, update.content),
      };
    case "tool_call":
    case "tool_call_update":
      return {
        ...state,
        entries: upsertToolCall(settleThinking(state.entries), update),
      };
    case "plan":
      return {
        ...state,
        entries: settleThinking(state.entries),
        plan: update.entries,
      };
  }
}

/** Applies events in order, starting from an empty timeline. */
export function reduceTimelineEvents(
  events: readonly TimelineEvent[]
): TimelineState {
  return events.reduce(reduceTimeline, INITIAL_TIMELINE_STATE);
}
