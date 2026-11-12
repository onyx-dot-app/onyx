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
  /** Agent message content. Adjacent text chunks are joined. */
  | { kind: "message"; content: AcpContentBlock[] }
  | { kind: "thinking"; text: string }
  | { kind: "tool"; toolCall: AcpToolCall };

export type AcpTimelineEntry = TimelineEntry<AcpTimelinePayload>;

export interface TimelineState {
  /** Messages, thinking blocks and tool calls, in arrival order. */
  entries: AcpTimelineEntry[];
  /** The latest plan. */
  plan: AcpPlanEntry[];
  /** Set when the turn ends. */
  stopReason: AcpStopReason | null;
  /** Set when the turn fails. */
  error: string | null;
}

export const INITIAL_TIMELINE_STATE: TimelineState = {
  entries: [],
  plan: [],
  stopReason: null,
  error: null,
};

type ChunkKind = "message" | "thinking";

function isChunkEntry(entry: AcpTimelineEntry): boolean {
  return entry.payload.kind === "message" || entry.payload.kind === "thinking";
}

/** Ends every open message or thinking entry, except `keepId`. */
function settleChunks(
  entries: AcpTimelineEntry[],
  keepId: string | null = null
): AcpTimelineEntry[] {
  if (!entries.some((e) => e.status === "streaming" && isChunkEntry(e))) {
    return entries;
  }
  return entries.map((entry) =>
    entry.status === "streaming" && isChunkEntry(entry) && entry.id !== keepId
      ? { ...entry, status: "done" }
      : entry
  );
}

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

/**
 * Applies the fields an update sets. A field that is left out or `null` keeps
 * its value: the wire sends unset ACP fields as `null`.
 */
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
    rawInput: update.rawInput ?? toolCall.rawInput,
    rawOutput: update.rawOutput ?? toolCall.rawOutput,
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
    rawInput: null,
    rawOutput: null,
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

function chunkPayload(
  kind: ChunkKind,
  content: AcpContentBlock[]
): AcpTimelinePayload {
  if (kind === "message") return { kind, content };
  const text = content
    .map((block) => (block.type === "text" ? block.text : ""))
    .join("");
  return { kind, text };
}

function chunkContent(entry: AcpTimelineEntry): AcpContentBlock[] {
  switch (entry.payload.kind) {
    case "message":
      return entry.payload.content;
    case "thinking":
      return [{ type: "text", text: entry.payload.text }];
    case "tool":
      return [];
  }
}

/** Adds a block, joining it to the last block when both are text. */
function appendBlock(
  content: AcpContentBlock[],
  block: AcpContentBlock
): AcpContentBlock[] {
  const last = content[content.length - 1];
  if (last?.type === "text" && block.type === "text") {
    return [...content.slice(0, -1), { ...last, text: last.text + block.text }];
  }
  return [...content, block];
}

/**
 * Adds a message or thought chunk. A chunk with a part id updates that part's
 * entry, and its snapshot text replaces the text received so far. A chunk
 * without one continues the last entry of the same kind while it streams.
 */
function appendChunk(
  entries: AcpTimelineEntry[],
  kind: ChunkKind,
  block: AcpContentBlock,
  meta: AcpMeta | undefined
): AcpTimelineEntry[] {
  const partId = meta?.onyx?.partId;
  const snapshot = meta?.onyx?.snapshotText;
  // Thoughts are text; other block types carry nothing to show.
  if (kind === "thinking" && block.type !== "text" && snapshot === undefined) {
    return entries;
  }

  const index = partId
    ? entries.findIndex((e) => e.id === `part:${partId}`)
    : entries.length - 1;
  const target = entries[index];
  const continues =
    target !== undefined &&
    target.payload.kind === kind &&
    (partId !== undefined || target.status === "streaming");

  if (!continues) {
    const content: AcpContentBlock[] =
      snapshot !== undefined ? [{ type: "text", text: snapshot }] : [block];
    const id = partId ? `part:${partId}` : `${kind}-${entries.length}`;
    return [
      ...settleChunks(entries),
      {
        id,
        status: "streaming",
        groupId: null,
        payload: chunkPayload(kind, content),
      },
    ];
  }

  const content =
    snapshot !== undefined
      ? [{ type: "text" as const, text: snapshot }]
      : appendBlock(chunkContent(target), block);
  const updated: AcpTimelineEntry = {
    ...target,
    payload: chunkPayload(kind, content),
  };
  return settleChunks(
    entries.map((entry, i) => (i === index ? updated : entry)),
    updated.id
  );
}

/** Applies one event. Pure: returns a new state and never mutates `state`. */
export function reduceTimeline(
  state: TimelineState,
  event: TimelineEvent
): TimelineState {
  if (event.type === "stop") {
    return {
      ...state,
      entries: settleChunks(state.entries),
      stopReason: event.stopReason,
    };
  }
  if (event.type === "error") {
    return {
      ...state,
      entries: settleChunks(state.entries),
      error: event.message,
    };
  }

  const { update } = event;
  switch (update.sessionUpdate) {
    case "agent_thought_chunk":
      return {
        ...state,
        entries: appendChunk(
          state.entries,
          "thinking",
          update.content,
          update._meta
        ),
      };
    case "agent_message_chunk":
      return {
        ...state,
        entries: appendChunk(
          state.entries,
          "message",
          update.content,
          update._meta
        ),
      };
    case "tool_call":
    case "tool_call_update":
      return {
        ...state,
        entries: upsertToolCall(settleChunks(state.entries), update),
      };
    case "plan":
      return {
        ...state,
        entries: settleChunks(state.entries),
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
