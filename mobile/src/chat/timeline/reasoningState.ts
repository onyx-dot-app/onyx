// Ported from web's `ReasoningRenderer` helpers; kept out of the renderer so it stays
// reanimated-free and unit-testable.
import { Packet, PacketType, ReasoningDelta } from "@/chat/streamingModels";

// Longer headings are prose, not titles, and overflow the step header.
const MAX_TITLE_LENGTH = 60;

export interface ReasoningState {
  hasStart: boolean;
  hasEnd: boolean;
  content: string;
}

export interface FirstParagraph {
  // Set only when the reasoning opens with a short markdown heading.
  title: string | null;
  remainingContent: string;
}

export function extractFirstParagraph(content: string): FirstParagraph {
  if (!content || content.trim().length === 0) {
    return { title: null, remainingContent: content };
  }

  const trimmed = content.trim();
  const firstLine = trimmed.split(/\n\n|\n/)[0]?.trim();
  if (!firstLine) {
    return { title: null, remainingContent: content };
  }

  if (!/^#+\s/.test(firstLine)) {
    return { title: null, remainingContent: content };
  }

  const cleanTitle = firstLine.replace(/^#+\s*/, "").trim();
  if (cleanTitle.length > MAX_TITLE_LENGTH) {
    return { title: null, remainingContent: content };
  }

  return {
    title: cleanTitle,
    remainingContent: trimmed.slice(firstLine.length).replace(/^\n+/, ""),
  };
}

// Resolves one step's reasoning text from the processor's grouped packets. The message row re-runs
// this every flush so an open full-text reader tracks the stream instead of freezing at open time.
export function resolveGroupReasoning(
  groupedPacketsMap: Map<string, Packet[]>,
  groupKey: string | null,
): string | null {
  if (groupKey === null) {
    return null;
  }
  const group = groupedPacketsMap.get(groupKey);
  return group ? constructCurrentReasoningState(group).content : null;
}

export function constructCurrentReasoningState(
  packets: Packet[],
): ReasoningState {
  const hasStart = packets.some(
    (packet) => packet.obj.type === PacketType.REASONING_START,
  );
  // section_end is client-synthesized and closes most groups; reasoning_done is the backend's own.
  const hasEnd = packets.some(
    (packet) =>
      packet.obj.type === PacketType.SECTION_END ||
      packet.obj.type === PacketType.ERROR ||
      packet.obj.type === PacketType.REASONING_DONE,
  );
  const content = packets
    .filter((packet) => packet.obj.type === PacketType.REASONING_DELTA)
    .map((packet) => (packet.obj as ReasoningDelta).reasoning)
    .join("");

  return { hasStart, hasEnd, content };
}
