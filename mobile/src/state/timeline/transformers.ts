// transformers.ts — pure packet-group → step/turn shaping.
//
// Ported verbatim from web:
//   web/src/app/app/message/messageComponents/timeline/transformers.ts
// Reshapes the processor's GroupedPacket[] into TransformedStep[] and buckets
// them into TurnGroup[] (parallel tools share a turn_index, differ by tab_index).

import { GroupedPacket } from "@/state/timeline/packetProcessor";

/** Transformed step data ready for rendering. */
export interface TransformedStep {
  /** Unique key for rendering: `${turnIndex}-${tabIndex}`. */
  key: string;
  turnIndex: number;
  tabIndex: number;
  packets: GroupedPacket["packets"];
}

/** Steps grouped by turn_index; isParallel when more than one step shares a turn. */
export interface TurnGroup {
  turnIndex: number;
  steps: TransformedStep[];
  isParallel: boolean;
}

export function transformPacketGroup(group: GroupedPacket): TransformedStep {
  return {
    key: `${group.turn_index}-${group.tab_index}`,
    turnIndex: group.turn_index,
    tabIndex: group.tab_index,
    packets: group.packets,
  };
}

export function transformPacketGroups(
  groups: GroupedPacket[]
): TransformedStep[] {
  return groups.map(transformPacketGroup);
}

/** Group transformed steps by turn_index to detect parallel tools. */
export function groupStepsByTurn(steps: TransformedStep[]): TurnGroup[] {
  const turnMap = new Map<number, TransformedStep[]>();

  for (const step of steps) {
    const existing = turnMap.get(step.turnIndex);
    if (existing) {
      existing.push(step);
    } else {
      turnMap.set(step.turnIndex, [step]);
    }
  }

  const result: TurnGroup[] = [];
  const sortedTurnIndices = Array.from(turnMap.keys()).sort((a, b) => a - b);

  for (const turnIndex of sortedTurnIndices) {
    const stepsForTurn = turnMap.get(turnIndex)!;
    stepsForTurn.sort((a, b) => a.tabIndex - b.tabIndex);

    result.push({
      turnIndex,
      steps: stepsForTurn,
      isParallel: stepsForTurn.length > 1,
    });
  }

  return result;
}
