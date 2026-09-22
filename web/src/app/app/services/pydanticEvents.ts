import { Packet, PacketType } from "@/app/app/services/streamingModels";

export function nativePartKind(packet: Packet): string | undefined {
  if (packet.obj.type !== PacketType.PYDANTIC_AI) return undefined;
  const event = packet.obj.event;
  if (event.event_kind === "part_start" || event.event_kind === "part_end") {
    return event.part.part_kind;
  }
  if (event.event_kind === "part_delta") return event.delta.part_delta_kind;
  return undefined;
}

export function isNativeText(packet: Packet): boolean {
  return nativePartKind(packet) === "text";
}

export function isNativeThinking(packet: Packet): boolean {
  return nativePartKind(packet) === "thinking";
}

export function nativeContent(
  packet: Packet,
  kind: "text" | "thinking"
): string {
  if (packet.obj.type !== PacketType.PYDANTIC_AI) return "";
  const event = packet.obj.event;
  if (event.event_kind === "part_start" && event.part.part_kind === kind) {
    return event.part.content;
  }
  if (
    event.event_kind === "part_delta" &&
    event.delta.part_delta_kind === kind
  ) {
    return event.delta.content_delta ?? "";
  }
  // Part-end includes the full accumulated content and must not append it again.
  return "";
}

export function nativePartEnded(packet: Packet): boolean {
  return (
    packet.obj.type === PacketType.PYDANTIC_AI &&
    packet.obj.event.event_kind === "part_end"
  );
}

export function isNativeAnswer(packet: Packet): boolean {
  if (!isNativeText(packet) || packet.obj.type !== PacketType.PYDANTIC_AI)
    return false;
  return (
    packet.placement.sub_turn_index == null &&
    (packet.obj.phase == null ||
      packet.obj.phase === "chat" ||
      packet.obj.phase === "clarification" ||
      packet.obj.phase === "report")
  );
}

export function isNativeNarration(packet: Packet): boolean {
  return (
    isNativeText(packet) &&
    packet.obj.type === PacketType.PYDANTIC_AI &&
    packet.obj.phase === "research"
  );
}
