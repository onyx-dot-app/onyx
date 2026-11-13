import { GroupedPacket } from "@/app/app/message/messageComponents/timeline/hooks/packetProcessor";
import {
  CodeModeProgram,
  NestedCall,
} from "@/app/app/message/messageComponents/timeline/packetHelpers";

/**
 * Transformed step data ready for rendering
 */
export interface TransformedStep {
  /** Unique key for React rendering */
  key: string;
  /** Key of the packet group the step's packets come from */
  groupKey: string;
  /** Turn index from packet placement */
  turnIndex: number;
  /** Tab index for parallel tools */
  tabIndex: number;
  /** The step's own packets, without the packets of nested calls */
  packets: GroupedPacket["packets"];
  /** Tool calls nested under the step, ordered by sub_turn_index */
  nestedCalls: NestedCall[];
  /** Every packet of the step, nested calls included, in stream order */
  streamPackets: GroupedPacket["streamPackets"];
  /** The program of a code mode step; null for other steps */
  codeMode: CodeModeProgram | null;
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
  const key = `${group.turn_index}-${group.tab_index}`;
  return {
    key,
    groupKey: key,
    turnIndex: group.turn_index,
    tabIndex: group.tab_index,
    packets: group.packets,
    nestedCalls: group.nestedCalls,
    streamPackets: group.streamPackets,
    codeMode: group.codeMode,
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
 *
 * @example
 * // Input: TransformedStep[]
 * // ┌──────────────────────────────────────────┐
 * // │ [0] key="0-0" turnIndex=0 tabIndex=0     │
 * // │ [1] key="0-1" turnIndex=0 tabIndex=1     │
 * // │ [2] key="1-0" turnIndex=1 tabIndex=0     │
 * // └──────────────────────────────────────────┘
 * //
 * // Step 1: Build Map<turnIndex, TransformedStep[]>
 * // ┌─────────────────────────────────────────────┐
 * // │ turnMap = {                                 │
 * // │   0 → [step(0-0), step(0-1)]               │
 * // │   1 → [step(1-0)]                          │
 * // │ }                                          │
 * // └─────────────────────────────────────────────┘
 * //
 * // Step 2: Sort turn indices & steps by tabIndex
 * //
 * // Step 3: Build TurnGroup[] with isParallel flag
 * // ┌─────────────────────────────────────────────┐
 * // │ Output: TurnGroup[]                         │
 * // ├─────────────────────────────────────────────┤
 * // │ [0] turnIndex=0                             │
 * // │     steps=[0-0, 0-1]                        │
 * // │     isParallel=true  ← 2 steps = parallel   │
 * // │                                             │
 * // │ [1] turnIndex=1                             │
 * // │     steps=[1-0]                             │
 * // │     isParallel=false ← 1 step = sequential  │
 * // └─────────────────────────────────────────────┘
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
  /** A program runs between tool calls: an observation runs it (see
   * CodeModeProgram.running) and none of its cell's calls is in flight. The
   * program has no step of its own, so only the timeline header shows this. */
  codeModeWorking: boolean;
}

// Steps built for nested calls, reused while the call object, key and
// position are unchanged, so memoized step renderers skip them.
const callSteps = new WeakMap<NestedCall, TransformedStep>();

function callStep(
  call: NestedCall,
  key: string,
  groupKey: string,
  turnIndex: number
): TransformedStep {
  const cached = callSteps.get(call);
  if (
    cached &&
    cached.key === key &&
    cached.groupKey === groupKey &&
    cached.turnIndex === turnIndex
  ) {
    return cached;
  }
  const step: TransformedStep = {
    key,
    groupKey,
    turnIndex,
    tabIndex: 0,
    packets: call.packets,
    nestedCalls: [],
    streamPackets: call.packets,
    codeMode: null,
  };
  callSteps.set(call, step);
  return step;
}

/**
 * Shows code mode as the tool calls it makes. Each nested call of a program
 * becomes its own step, as a direct call would; the program itself has no
 * step. A call is its cell and sub_turn_index, as CodeModeRenderer in
 * backend/onyx/chat/renderer.py states: a later report replaces an earlier one
 * in place. A report of a running call
 * can hold only its start, so it replaces only a report with no more packets;
 * a complete report always replaces. Steps get sequential turn indices in
 * stream order; direct steps of one turn keep a shared index, so parallel
 * calls stay grouped.
 */
export function expandCodeModeSteps(
  steps: TransformedStep[]
): CodeModeTimeline {
  const out: TransformedStep[] = [];
  // Where each call's step sits in `out`, the turn index it got first, its
  // cell, and the report it shows.
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
        out.push(callStep(call, key, step.groupKey, turnIndex));
      } else if (
        call.complete ||
        call.packets.length >= slot.call.packets.length
      ) {
        slot.call = call;
        out[slot.index] = callStep(call, key, step.groupKey, slot.turnIndex);
      }
    }
  }

  const slots = Array.from(slotByKey.values());
  const codeModeWorking = Array.from(runningCells).some((cellKey) =>
    slots.every((slot) => slot.cellKey !== cellKey || slot.call.complete)
  );
  return { steps: out, codeModeWorking };
}
