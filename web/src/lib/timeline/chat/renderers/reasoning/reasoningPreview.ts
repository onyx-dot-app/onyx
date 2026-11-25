import { type Packet, PacketType } from "@/app/app/services/streamingModels";

/** A section title: a line that opens with bold text, or a closed heading. */
const SECTION_TITLE = /^(?:\*\*([^*\n]+)\*\*|#{1,6}[ \t]+([^\n]+)\n)/gm;

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
 */
export function reasoningPreview(text: string): string {
  let title = "";
  for (const match of text.matchAll(SECTION_TITLE)) {
    const found = (match[1] ?? match[2] ?? "")
      .replace(/[*_`]/g, "")
      .replace(/\s+/g, " ")
      .trim()
      .replace(/:$/, "");
    if (found) title = found;
  }
  return title;
}
