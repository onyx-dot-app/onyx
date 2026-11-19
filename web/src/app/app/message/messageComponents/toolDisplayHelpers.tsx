import type { useTranslations } from "next-intl";
import { Packet, PacketType } from "@/app/app/services/streamingModels";
import { isGroupEndPacket } from "@/lib/timeline/chat/packetHelpers";
import { isDisplayPacket, isToolPacket } from "@/app/app/services/packetUtils";
import { SvgXCircle } from "@opal/icons";

/**
 * Check if a packet group contains an ERROR packet (tool failed)
 */
export function hasToolError(packets: Packet[]): boolean {
  return packets.some((p) => p.obj.type === PacketType.ERROR);
}

/**
 * Check if a tool group is complete: a parent-level SECTION_END or ERROR
 * arrived. Nested calls end with their own SECTION_END and do not count.
 */
export function isToolComplete(packets: Packet[]): boolean {
  return packets.some(isGroupEndPacket);
}

/**
 * Get an error icon for failed tools
 */
export function getToolErrorIcon(): React.ReactNode {
  return <SvgXCircle className="w-3.5 h-3.5 text-error" />;
}

export function getToolKey(turn_index: number, tab_index: number = 0): string {
  return `${turn_index}-${tab_index}`;
}

export function parseToolKey(key: string): {
  turn_index: number;
  tab_index: number;
} {
  const parts = key.split("-");
  return {
    turn_index: parseInt(parts[0] ?? "0", 10),
    tab_index: parseInt(parts[1] ?? "0", 10),
  };
}

/**
 * The packet that names a step's activity. Debug and approval packets share
 * the step's placement but never name it.
 */
export function firstActivityPacket(packets: Packet[]): Packet | undefined {
  return packets.find(
    (packet) => isToolPacket(packet, false) || isDisplayPacket(packet)
  );
}

export type TimelineTranslate = ReturnType<
  typeof useTranslations<"chat.messages.timeline">
>;
