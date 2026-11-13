// GroupedPacket → step → turn-group transforms + parallel detection. Port of web's transformers.

import { GroupedPacket } from "@/chat/messageProcessor";
import { CodeModeProgram, NestedCall } from "@/chat/timeline/packetHelpers";

export interface TransformedStep {
  key: string;
  turnIndex: number;
  tabIndex: number;
  packets: GroupedPacket["packets"];
  // Tool calls nested under the step, ordered by sub_turn_index
  nestedCalls: NestedCall[];
  // The program of a code mode step; null for other steps
  codeMode: CodeModeProgram | null;
}

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
    nestedCalls: group.nestedCalls,
    codeMode: group.codeMode,
  };
}

export function transformPacketGroups(
  groups: GroupedPacket[],
): TransformedStep[] {
  return groups.map(transformPacketGroup);
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

export interface CodeModeTimeline {
  steps: TransformedStep[];
  /** A program runs between tool calls: an observation runs it (see CodeModeProgram.running) and
   * none of its cell's calls is in flight. The program has no step of its own, so only the
   * timeline header shows this. */
  codeModeWorking: boolean;
}

function callStep(
  call: NestedCall,
  key: string,
  turnIndex: number,
): TransformedStep {
  return {
    key,
    turnIndex,
    tabIndex: 0,
    packets: call.packets,
    nestedCalls: [],
    codeMode: null,
  };
}

/**
 * Shows code mode as the tool calls it makes. Each nested call of a program becomes its own
 * step, as a direct call would; the program itself has no step. A call is its cell and
 * sub_turn_index, as CodeModeRenderer in backend/onyx/chat/renderer.py states: a later report
 * replaces an earlier one in place. A report of
 * a running call can hold only its start, so it replaces only a report with no more packets; a
 * complete report always replaces. Steps get sequential turn indices in stream order; direct steps
 * of one turn keep a shared index.
 */
export function expandCodeModeSteps(
  steps: TransformedStep[],
): CodeModeTimeline {
  const out: TransformedStep[] = [];
  // Where each call's step sits in `out`, the turn index it got first, its cell, and the report
  // it shows.
  const slotByKey = new Map<
    string,
    { index: number; turnIndex: number; cellKey: string; call: NestedCall }
  >();
  const directTurns = new Map<number, number>();
  // The key of each cell's first step; the keys of its calls derive from it.
  const cellKeys = new Map<number, string>();
  // Cell keys of observations whose program is running.
  const runningCells = new Set<string>();
  let nextTurn = 0;

  for (const step of steps) {
    const program = step.codeMode;
    if (program === null) {
      let turn = directTurns.get(step.turnIndex);
      if (turn === undefined) {
        turn = nextTurn++;
        directTurns.set(step.turnIndex, turn);
      }
      out.push(turn === step.turnIndex ? step : { ...step, turnIndex: turn });
      continue;
    }

    const cellId = program.cellId;
    const cellKey =
      (cellId === null ? undefined : cellKeys.get(cellId)) ?? step.key;
    if (cellId !== null) cellKeys.set(cellId, cellKey);
    if (program.running) {
      runningCells.add(cellKey);
    } else {
      runningCells.delete(cellKey);
    }

    for (const call of step.nestedCalls) {
      const key = `${cellKey}-${call.subTurnIndex}`;
      const slot = slotByKey.get(key);
      if (slot === undefined) {
        const turnIndex = nextTurn++;
        slotByKey.set(key, {
          index: out.length,
          turnIndex,
          cellKey,
          call,
        });
        out.push(callStep(call, key, turnIndex));
      } else if (
        call.complete ||
        call.packets.length >= slot.call.packets.length
      ) {
        slot.call = call;
        out[slot.index] = callStep(call, key, slot.turnIndex);
      }
    }
  }

  const slots = Array.from(slotByKey.values());
  const codeModeWorking = Array.from(runningCells).some((cellKey) =>
    slots.every((slot) => slot.cellKey !== cellKey || slot.call.complete),
  );
  return { steps: out, codeModeWorking };
}
