// Shared builders for the timeline hook tests (not a suite — no `.test.` suffix, so jest skips it).

import { Packet, PacketType } from "@/chat/streamingModels";
import { TransformedStep, TurnGroup } from "@/chat/timeline/transformers";

export function makePacket(
  type: PacketType,
  placement: {
    turn_index: number;
    tab_index?: number;
    sub_turn_index?: number | null;
  } = { turn_index: 0 },
  extra: Record<string, unknown> = {},
): Packet {
  return {
    placement: { tab_index: 0, ...placement },
    obj: { type, ...extra } as unknown as Packet["obj"],
  };
}

export function makeStep(
  turnIndex: number,
  tabIndex: number,
  packets: Packet[],
): TransformedStep {
  return {
    key: `${turnIndex}-${tabIndex}`,
    turnIndex,
    tabIndex,
    packets,
  };
}

export function makeTurn(
  turnIndex: number,
  steps: TransformedStep[],
): TurnGroup {
  return { turnIndex, steps, isParallel: steps.length > 1 };
}
