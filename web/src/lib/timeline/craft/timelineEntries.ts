import type {
  StreamItem,
  ToolCallState,
  ToolCallStatus,
} from "@/app/craft/types/displayTypes";
import type { TimelineEntry, TimelineEntryStatus } from "@/lib/timeline/types";

export type CraftTimelinePayload =
  | { kind: "tool"; toolCall: ToolCallState }
  | { kind: "thinking"; content: string; isStreaming: boolean };

export type CraftTimelineEntry = TimelineEntry<CraftTimelinePayload>;

/** Stream items that render inline in the transcript, outside the rail. */
export type CraftInlineItem = Exclude<
  StreamItem,
  { type: "tool_call" } | { type: "thinking" }
>;

export type CraftTranscriptBlock =
  | { kind: "steps"; id: string; entries: CraftTimelineEntry[] }
  | { kind: "item"; item: CraftInlineItem };

function toolCallStatus(status: ToolCallStatus): TimelineEntryStatus {
  switch (status) {
    case "pending":
    case "in_progress":
      return "streaming";
    case "failed":
      return "error";
    case "cancelled":
      return "stopped";
    case "completed":
      return "done";
  }
}

/**
 * Tool calls and thinking become timeline entries, keyed by tool-call id or
 * stream item id. Craft has no parallel tabs, so no entry has a group.
 */
export function toCraftTimelineEntry(
  item: StreamItem
): CraftTimelineEntry | null {
  if (item.type === "tool_call") {
    return {
      id: item.toolCall.id,
      status: toolCallStatus(item.toolCall.status),
      groupId: null,
      payload: { kind: "tool", toolCall: item.toolCall },
    };
  }
  if (item.type === "thinking") {
    if (!item.content) return null;
    return {
      id: item.id,
      status: item.isStreaming ? "streaming" : "done",
      groupId: null,
      payload: {
        kind: "thinking",
        content: item.content,
        isStreaming: item.isStreaming,
      },
    };
  }
  return null;
}

/**
 * Splits a turn's stream items into rail blocks and inline items, in stream
 * order. Consecutive entries share one rail block; any inline item ends it.
 */
export function buildCraftTranscript(
  items: readonly StreamItem[]
): CraftTranscriptBlock[] {
  const blocks: CraftTranscriptBlock[] = [];
  for (const item of items) {
    if (item.type === "tool_call" || item.type === "thinking") {
      const entry = toCraftTimelineEntry(item);
      if (!entry) continue;
      const last = blocks[blocks.length - 1];
      if (last?.kind === "steps") {
        last.entries.push(entry);
      } else {
        blocks.push({ kind: "steps", id: entry.id, entries: [entry] });
      }
      continue;
    }
    blocks.push({ kind: "item", item });
  }
  return blocks;
}
