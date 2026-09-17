// GroupedItem → step → turn-group transforms + parallel detection. Port of web's transformers.

import { GroupedItem } from "@/chat/messageProcessor";

export interface TransformedStep {
  key: string;
  turnIndex: number;
  tabIndex: number;
  items: GroupedItem["items"];
}

export interface TurnGroup {
  turnIndex: number;
  steps: TransformedStep[];
  isParallel: boolean;
}

export function transformItemGroup(group: GroupedItem): TransformedStep {
  return {
    key: `${group.turn_index}-${group.tab_index}`,
    turnIndex: group.turn_index,
    tabIndex: group.tab_index,
    items: group.items,
  };
}

export function transformItemGroups(groups: GroupedItem[]): TransformedStep[] {
  return groups.map(transformItemGroup);
}

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
