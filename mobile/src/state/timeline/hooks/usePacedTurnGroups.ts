/* eslint-disable react-hooks/refs, react-hooks/immutability -- Intentional:
   all pacing state lives in a ref (mutated during effects/timers, read during
   render via a revealTrigger counter), and paced arrays are reference-stabilized
   in place. Ported verbatim from the battle-tested web usePacedTurnGroups. */
// Mirrors web usePacedTurnGroups. Staggered (200ms) reveal of timeline steps.
// STOP flushes everything; history (stopPacketSeen on first render) bypasses
// pacing entirely. Output arrays are reference-stabilized to avoid re-renders.

import { useRef, useState, useEffect, useCallback, useMemo } from "react";
import { PacketType } from "@/lib/types";
import { GroupedPacket } from "@/state/timeline/packetProcessor";
import { TurnGroup, TransformedStep } from "@/state/timeline/transformers";

const PACING_DELAY_MS = 200;

const TOOL_START_PACKET_TYPES = new Set<PacketType>([
  PacketType.SEARCH_TOOL_START,
  PacketType.FETCH_TOOL_START,
  PacketType.PYTHON_TOOL_START,
  PacketType.CUSTOM_TOOL_START,
  PacketType.FILE_READER_START,
  PacketType.REASONING_START,
  PacketType.IMAGE_GENERATION_TOOL_START,
  PacketType.DEEP_RESEARCH_PLAN_START,
  PacketType.RESEARCH_AGENT_START,
  PacketType.MEMORY_TOOL_START,
  PacketType.MEMORY_TOOL_NO_ACCESS,
]);

function getStepPacketType(step: TransformedStep): PacketType | null {
  for (const packet of step.packets) {
    if (TOOL_START_PACKET_TYPES.has(packet.obj.type as PacketType)) {
      return packet.obj.type as PacketType;
    }
  }
  return null;
}

interface PacingState {
  revealedStepKeys: Set<string>;
  lastRevealedPacketType: PacketType | null;
  pendingSteps: TransformedStep[];
  pacingTimer: ReturnType<typeof setTimeout> | null;
  toolPacingComplete: boolean;
  stopPacketSeen: boolean;
  nodeId: string | null;
}

function createInitialPacingState(): PacingState {
  return {
    revealedStepKeys: new Set(),
    lastRevealedPacketType: null,
    pendingSteps: [],
    pacingTimer: null,
    toolPacingComplete: false,
    stopPacketSeen: false,
    nodeId: null,
  };
}

export function usePacedTurnGroups(
  toolTurnGroups: TurnGroup[],
  displayGroups: GroupedPacket[],
  stopPacketSeen: boolean,
  nodeId: number,
  finalAnswerComing: boolean
): {
  pacedTurnGroups: TurnGroup[];
  pacedDisplayGroups: GroupedPacket[];
  pacedFinalAnswerComing: boolean;
} {
  const stateRef = useRef<PacingState>(createInitialPacingState());
  const prevFinalAnswerComingRef = useRef(finalAnswerComing);
  const prevPacedRef = useRef<TurnGroup[]>([]);
  const [revealTrigger, setRevealTrigger] = useState(0);

  const nodeIdStr = String(nodeId);

  // Reset on nodeId change.
  if (stateRef.current.nodeId !== nodeIdStr) {
    if (stateRef.current.pacingTimer) {
      clearTimeout(stateRef.current.pacingTimer);
    }
    stateRef.current = createInitialPacingState();
    stateRef.current.nodeId = nodeIdStr;
    prevPacedRef.current = [];
  }

  const state = stateRef.current;

  const shouldBypassPacing =
    stopPacketSeen &&
    state.revealedStepKeys.size === 0 &&
    toolTurnGroups.length > 0;

  const revealNextPendingStep = useCallback(() => {
    const s = stateRef.current;

    if (s.pendingSteps.length > 0) {
      const stepToReveal = s.pendingSteps.shift()!;
      s.revealedStepKeys.add(stepToReveal.key);
      s.lastRevealedPacketType = getStepPacketType(stepToReveal);

      if (s.pendingSteps.length > 0) {
        s.pacingTimer = setTimeout(revealNextPendingStep, PACING_DELAY_MS);
        setRevealTrigger((t) => t + 1);
        return;
      }
    }

    s.toolPacingComplete = true;
    s.pacingTimer = null;
    setRevealTrigger((t) => t + 1);
  }, []);

  useEffect(() => {
    if (shouldBypassPacing) return;

    const s = stateRef.current;

    if (prevFinalAnswerComingRef.current && !finalAnswerComing) {
      s.toolPacingComplete = false;
    }
    prevFinalAnswerComingRef.current = finalAnswerComing;

    if (stopPacketSeen && !s.stopPacketSeen) {
      s.stopPacketSeen = true;

      if (s.pacingTimer) {
        clearTimeout(s.pacingTimer);
        s.pacingTimer = null;
      }

      for (const step of s.pendingSteps) {
        s.revealedStepKeys.add(step.key);
      }
      s.pendingSteps = [];
      s.toolPacingComplete = true;

      setRevealTrigger((t) => t + 1);
      return;
    }

    const allSteps: TransformedStep[] = [];
    for (const turnGroup of toolTurnGroups) {
      for (const step of turnGroup.steps) {
        allSteps.push(step);
      }
    }

    const newSteps: TransformedStep[] = [];
    const pendingKeys = new Set(s.pendingSteps.map((st) => st.key));

    for (const step of allSteps) {
      if (!s.revealedStepKeys.has(step.key) && !pendingKeys.has(step.key)) {
        newSteps.push(step);
      }
    }

    if (newSteps.length === 0) {
      if (allSteps.length === 0 && !s.toolPacingComplete) {
        s.toolPacingComplete = true;
        setRevealTrigger((t) => t + 1);
        return;
      }

      if (
        s.pendingSteps.length === 0 &&
        !s.pacingTimer &&
        allSteps.length > 0
      ) {
        const allRevealed = allSteps.every((st) =>
          s.revealedStepKeys.has(st.key)
        );
        if (allRevealed && !s.toolPacingComplete) {
          s.toolPacingComplete = true;
          setRevealTrigger((t) => t + 1);
        }
      }
      return;
    }

    for (const step of newSteps) {
      const stepType = getStepPacketType(step);

      if (s.revealedStepKeys.size === 0 && s.pendingSteps.length === 0) {
        s.revealedStepKeys.add(step.key);
        s.lastRevealedPacketType = stepType;
        setRevealTrigger((t) => t + 1);
        continue;
      }

      s.pendingSteps.push(step);

      if (!s.pacingTimer && s.pendingSteps.length === 1) {
        s.pacingTimer = setTimeout(revealNextPendingStep, PACING_DELAY_MS);
      }
    }

    if (s.pendingSteps.length > 0 || s.pacingTimer) {
      s.toolPacingComplete = false;
    }
  }, [
    toolTurnGroups,
    stopPacketSeen,
    finalAnswerComing,
    revealNextPendingStep,
    shouldBypassPacing,
  ]);

  useEffect(() => {
    return () => {
      if (stateRef.current.pacingTimer) {
        clearTimeout(stateRef.current.pacingTimer);
      }
    };
  }, []);

  const pacedTurnGroups = useMemo(() => {
    if (shouldBypassPacing) return toolTurnGroups;

    const result: TurnGroup[] = [];
    for (const turnGroup of toolTurnGroups) {
      const revealedSteps = turnGroup.steps.filter((step) =>
        state.revealedStepKeys.has(step.key)
      );
      if (revealedSteps.length > 0) {
        result.push({
          turnIndex: turnGroup.turnIndex,
          steps: revealedSteps,
          isParallel: revealedSteps.length > 1,
        });
      }
    }

    const prev = prevPacedRef.current;
    if (prev.length === result.length) {
      let allMatch = true;
      for (let i = 0; i < result.length; i++) {
        const oldGroup = prev[i]!;
        const newGroup = result[i]!;
        if (
          oldGroup.turnIndex === newGroup.turnIndex &&
          oldGroup.steps.length === newGroup.steps.length &&
          oldGroup.steps.every(
            (st, j) =>
              st.key === newGroup.steps[j]!.key &&
              st.packets.length === newGroup.steps[j]!.packets.length
          )
        ) {
          result[i] = oldGroup;
        } else {
          allMatch = false;
        }
      }
      if (allMatch) {
        return prev;
      }
    }

    prevPacedRef.current = result;
    return result;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [toolTurnGroups, revealTrigger, shouldBypassPacing]);

  const pacedDisplayGroups = useMemo(
    () =>
      shouldBypassPacing || state.toolPacingComplete || stopPacketSeen
        ? displayGroups
        : [],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      state.toolPacingComplete,
      displayGroups,
      revealTrigger,
      shouldBypassPacing,
      stopPacketSeen,
    ]
  );

  const pacedFinalAnswerComing = useMemo(
    () => (shouldBypassPacing || state.toolPacingComplete) && finalAnswerComing,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [state.toolPacingComplete, finalAnswerComing, revealTrigger, shouldBypassPacing]
  );

  return {
    pacedTurnGroups,
    pacedDisplayGroups,
    pacedFinalAnswerComing,
  };
}
