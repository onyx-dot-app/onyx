import type { ToolCallState } from "@/app/craft/types/displayTypes";
import type { TimelineEntry } from "@/lib/timeline/types";

export type CraftTimelinePayload =
  | { kind: "tool"; toolCall: ToolCallState }
  | { kind: "thinking"; content: string; isStreaming: boolean };

export type CraftTimelineEntry = TimelineEntry<CraftTimelinePayload>;
