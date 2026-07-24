// GroupedPacket → step → turn-group transforms + parallel detection. Faithful port of web's
// `web/.../timeline/transformers.ts` (mobile imports only).

import { GroupedPacket } from "@/chat/messageProcessor";

export interface TransformedStep {
  key: string; // `${turn_index}-${tab_index}`
  turnIndex: number;
  tabIndex: number;
  packets: GroupedPacket["packets"];
}

export interface TurnGroup {
  turnIndex: number;
  steps: TransformedStep[];
  // True when >1 step shares a turn_index (parallel execution).
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
  groups: GroupedPacket[],
): TransformedStep[] {
  return groups.map(transformPacketGroup);
}

// Group transformed steps by turn_index to detect parallel tools.
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
