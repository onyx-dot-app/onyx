import { type Packet, PacketType } from "@/app/app/services/streamingModels";

/** A section title: a line that opens with bold text, or a closed heading. */
const SECTION_TITLE = /(?:\*\*([^*\n]+)\*\*|#{1,6}[ \t]+([^\n]+)\n)/y;

/** The reasoning text a step's packets carry so far. */
export function reasoningText(packets: Packet[]): string {
  let text = "";
  for (const packet of packets) {
    if (packet.obj.type === PacketType.REASONING_DELTA) {
      text += packet.obj.reasoning;
    }
  }
  return text;
}

/**
 * The title of the reasoning's latest section, such as "Planning the answer"
 * for `**Planning the answer**` or `## Planning the answer`. It changes only
 * when a new section starts. Empty while the reasoning has no title.
 * It scans line starts from the end, so a long text with a late title is cheap.
 */
export function reasoningPreview(text: string): string {
  let lineStart = text.lastIndexOf("\n") + 1;
  for (;;) {
    SECTION_TITLE.lastIndex = lineStart;
    const match = SECTION_TITLE.exec(text);
    const found = match
      ? (match[1] ?? match[2] ?? "")
          .replace(/[*_`]/g, "")
          .replace(/\s+/g, " ")
          .trim()
          .replace(/:$/, "")
      : "";
    if (found) return found;
    if (lineStart === 0) return "";
    lineStart = lineStart === 1 ? 0 : text.lastIndexOf("\n", lineStart - 2) + 1;
  }
}
