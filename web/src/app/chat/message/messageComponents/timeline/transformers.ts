import { JSX } from "react";
import { GroupedPacket } from "../packetProcessor";
import { IconType } from "./AgentStep";
import {
  getIconForPackets,
  getNameForPackets,
  getIconTypeForPackets,
  isToolPacketGroup,
  isDisplayPacketGroup,
} from "./iconRegistry";

/**
 * Transformed step data ready for AgentStep rendering
 */
export interface TransformedStep {
  /** Unique key for React rendering */
  key: string;
  /** Turn index from packet placement */
  turnIndex: number;
  /** Tab index for parallel tools */
  tabIndex: number;
  /** Icon element for the step */
  icon: JSX.Element;
  /** Icon state (loading, complete, error) */
  iconType: IconType;
  /** Display name for the step header */
  name: string;
  /** Raw packets for content rendering */
  packets: GroupedPacket["packets"];
  /** Whether this is a tool step */
  isTool: boolean;
  /** Whether this is a display step (message, image) */
  isDisplay: boolean;
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
 * Transform a single GroupedPacket into step data
 */
export function transformPacketGroup(group: GroupedPacket): TransformedStep {
  return {
    key: `${group.turn_index}-${group.tab_index}`,
    turnIndex: group.turn_index,
    tabIndex: group.tab_index,
    icon: getIconForPackets(group.packets),
    iconType: getIconTypeForPackets(group.packets),
    name: getNameForPackets(group.packets),
    packets: group.packets,
    isTool: isToolPacketGroup(group.packets),
    isDisplay: isDisplayPacketGroup(group.packets),
  };
}

/**
 * Transform all packet groups into step data
 */
export function transformPacketGroups(
  groups: GroupedPacket[]
): TransformedStep[] {
  return groups.map(transformPacketGroup);
}

/**
 * Group transformed steps by turn_index to detect parallel tools
 */
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

  // Convert to sorted array
  const result: TurnGroup[] = [];
  const sortedTurnIndices = Array.from(turnMap.keys()).sort((a, b) => a - b);

  for (const turnIndex of sortedTurnIndices) {
    const stepsForTurn = turnMap.get(turnIndex)!;
    // Sort by tab_index within each turn
    stepsForTurn.sort((a, b) => a.tabIndex - b.tabIndex);

    result.push({
      turnIndex,
      steps: stepsForTurn,
      isParallel: stepsForTurn.length > 1,
    });
  }

  return result;
}

/**
 * Split steps into tool steps and display steps
 */
export function splitStepsByType(steps: TransformedStep[]): {
  toolSteps: TransformedStep[];
  displaySteps: TransformedStep[];
} {
  const toolSteps: TransformedStep[] = [];
  const displaySteps: TransformedStep[] = [];

  for (const step of steps) {
    if (step.isTool) {
      toolSteps.push(step);
    }
    if (step.isDisplay) {
      displaySteps.push(step);
    }
  }

  return { toolSteps, displaySteps };
}

/**
 * Get all tool turn groups (for timeline rendering)
 */
export function getToolTurnGroups(groups: GroupedPacket[]): TurnGroup[] {
  const allSteps = transformPacketGroups(groups);
  const { toolSteps } = splitStepsByType(allSteps);
  return groupStepsByTurn(toolSteps);
}

/**
 * Get all display steps (for message content rendering)
 */
export function getDisplaySteps(groups: GroupedPacket[]): TransformedStep[] {
  const allSteps = transformPacketGroups(groups);
  const { displaySteps } = splitStepsByType(allSteps);
  return displaySteps;
}
