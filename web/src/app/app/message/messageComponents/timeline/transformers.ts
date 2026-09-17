import { GroupedItem } from "@/app/app/message/messageComponents/timeline/hooks/packetProcessor";

/**
 * Transformed step data ready for rendering
 */
export interface TransformedStep {
  /** Unique key for React rendering */
  key: string;
  /** Turn index from packet placement */
  turnIndex: number;
  /** Tab index for parallel tools */
  tabIndex: number;
  /** Raw items for content rendering */
  items: GroupedItem["items"];
}

/**
 * Group steps by turn_index for detecting parallel tools
 */
export interface TurnGroup {
  turnIndex: number;
  steps: TransformedStep[];
  /** True if multiple steps have the same turn_index (parallel execution) */
  isParallel: boolean;
}

/**
 * Transform a single GroupedItem into step data
 */
export function transformPacketGroup(group: GroupedItem): TransformedStep {
  return {
    key: `${group.turn_index}-${group.tab_index}`,
    turnIndex: group.turn_index,
    tabIndex: group.tab_index,
    items: group.items,
  };
}

/**
 * Transform all packet groups into step data
 */
export function transformPacketGroups(
  groups: GroupedItem[]
): TransformedStep[] {
  return groups.map(transformPacketGroup);
}

/** Group concurrent tool items for the parallel timeline view. */
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
