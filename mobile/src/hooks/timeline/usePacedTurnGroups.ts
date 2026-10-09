// 200ms staggered reveal of timeline steps during streaming, for visual breathing room.
//
// Restructured from web (which reads pacing refs during render): mobile's react-hooks/refs lint
// forbids that, so the render-relevant fields (revealedStepKeys, toolPacingComplete) are useState
// PUBLISHED by the effect/callback (replacing web's revealTrigger bump), while the internal
// bookkeeping (pending queue, timer, flags) stays in a ref touched only in effects/callbacks.
// Behavior-preserving; web's prevPacedRef stabilization is dropped.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { GroupedPacket } from "@/chat/messageProcessor";
import { PacketType } from "@/chat/streamingModels";
import { TransformedStep, TurnGroup } from "@/chat/timeline/transformers";

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

// Internal pacing bookkeeping — lives in a ref, touched only inside effects/callbacks.
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

export interface UsePacedTurnGroupsResult {
  pacedTurnGroups: TurnGroup[];
  pacedDisplayGroups: GroupedPacket[];
  pacedFinalAnswerComing: boolean;
}

export function usePacedTurnGroups(
  toolTurnGroups: TurnGroup[],
  displayGroups: GroupedPacket[],
  stopPacketSeen: boolean,
  nodeId: number,
  finalAnswerComing: boolean,
): UsePacedTurnGroupsResult {
  const stateRef = useRef<PacingState>(createInitialPacingState());

  // Track previous finalAnswerComing to detect tool-after-message transitions (effect-only ref).
  const prevFinalAnswerComingRef = useRef(finalAnswerComing);

  // Published mirrors of the ref's render-relevant fields (web read the ref during render).
  const [revealedStepKeys, setRevealedStepKeys] = useState<Set<string>>(
    () => new Set(),
  );
  const [toolPacingComplete, setToolPacingComplete] = useState(false);

  const nodeIdStr = String(nodeId);

  // Message switch: reset the published mirrors synchronously during render (React re-renders before
  // commit), so the transition frame can't flash the previous node's revealed steps or answer. The
  // ref + timer reset and reprocessing happen in the effect below.
  const [prevNodeIdStr, setPrevNodeIdStr] = useState(nodeIdStr);
  if (prevNodeIdStr !== nodeIdStr) {
    setPrevNodeIdStr(nodeIdStr);
    setRevealedStepKeys(new Set());
    setToolPacingComplete(false);
  }

  // Publish the ref's working set/flag to state so the next render reflects them.
  const publish = useCallback(() => {
    const state = stateRef.current;
    setRevealedStepKeys(new Set(state.revealedStepKeys));
    setToolPacingComplete(state.toolPacingComplete);
  }, []);

  // Holds the latest reveal fn so the recursive timer can call it without a forward self-reference
  // (mobile's react-hooks lint forbids referencing a value before it's declared).
  const revealNextPendingStepRef = useRef<() => void>(() => {});

  // Reveal one queued step per fire, then reschedule if more remain.
  const revealNextPendingStep = useCallback(() => {
    const state = stateRef.current;

    if (state.pendingSteps.length > 0) {
      const stepToReveal = state.pendingSteps.shift()!;
      state.revealedStepKeys.add(stepToReveal.key);
      state.lastRevealedPacketType = getStepPacketType(stepToReveal);

      if (state.pendingSteps.length > 0) {
        state.pacingTimer = setTimeout(
          () => revealNextPendingStepRef.current(),
          PACING_DELAY_MS,
        );
        publish();
        return;
      }
    }

    state.toolPacingComplete = true;
    state.pacingTimer = null;
    publish();
  }, [publish]);

  useEffect(() => {
    revealNextPendingStepRef.current = revealNextPendingStep;
  }, [revealNextPendingStep]);

  // History reload: a message already complete on first render (stop seen, nothing revealed, steps
  // exist) reveals everything at once and stays bypassed.
  const shouldBypassPacing =
    stopPacketSeen && revealedStepKeys.size === 0 && toolTurnGroups.length > 0;

  // Process incoming turn groups (reset → transition → stop-flush → reveal/queue).
  useEffect(() => {
    // Reset the ref bookkeeping + timer on a message switch (the published mirrors were already
    // cleared synchronously during render, above).
    if (stateRef.current.nodeId !== nodeIdStr) {
      if (stateRef.current.pacingTimer) {
        clearTimeout(stateRef.current.pacingTimer);
      }
      stateRef.current = createInitialPacingState();
      stateRef.current.nodeId = nodeIdStr;
    }

    const state = stateRef.current;

    // Recompute bypass from the (post-reset) ref rather than the render-time published value.
    const bypassNow =
      stopPacketSeen &&
      state.revealedStepKeys.size === 0 &&
      toolTurnGroups.length > 0;
    if (bypassNow) return;

    // Tool-after-message: hide the answer until the new tools finish pacing. Publish the flag, or the
    // mirror lags the ref and the answer shows through the pacing gap (web re-reads the live ref).
    if (prevFinalAnswerComingRef.current && !finalAnswerComing) {
      state.toolPacingComplete = false;
      setToolPacingComplete(false);
    }
    prevFinalAnswerComingRef.current = finalAnswerComing;

    // STOP: flush every pending step immediately.
    if (stopPacketSeen && !state.stopPacketSeen) {
      state.stopPacketSeen = true;

      if (state.pacingTimer) {
        clearTimeout(state.pacingTimer);
        state.pacingTimer = null;
      }
      for (const step of state.pendingSteps) {
        state.revealedStepKeys.add(step.key);
      }
      state.pendingSteps = [];
      state.toolPacingComplete = true;

      publish();
      return;
    }

    const allSteps: TransformedStep[] = [];
    for (const turnGroup of toolTurnGroups) {
      for (const step of turnGroup.steps) {
        allSteps.push(step);
      }
    }

    // New = not yet revealed and not already queued.
    const pendingKeys = new Set(state.pendingSteps.map((s) => s.key));
    const newSteps: TransformedStep[] = [];
    for (const step of allSteps) {
      if (!state.revealedStepKeys.has(step.key) && !pendingKeys.has(step.key)) {
        newSteps.push(step);
      }
    }

    if (newSteps.length === 0) {
      // No tool steps — complete immediately so a tool-less answer can render.
      if (allSteps.length === 0 && !state.toolPacingComplete) {
        state.toolPacingComplete = true;
        publish();
        return;
      }

      // All steps revealed, nothing pending or timing — pacing complete.
      if (
        state.pendingSteps.length === 0 &&
        !state.pacingTimer &&
        allSteps.length > 0
      ) {
        const allRevealed = allSteps.every((s) =>
          state.revealedStepKeys.has(s.key),
        );
        if (allRevealed && !state.toolPacingComplete) {
          state.toolPacingComplete = true;
          publish();
        }
      }
      return;
    }

    for (const step of newSteps) {
      const stepType = getStepPacketType(step);

      // First step ever — reveal immediately.
      if (
        state.revealedStepKeys.size === 0 &&
        state.pendingSteps.length === 0
      ) {
        state.revealedStepKeys.add(step.key);
        state.lastRevealedPacketType = stepType;
        publish();
        continue;
      }

      state.pendingSteps.push(step);
      if (!state.pacingTimer && state.pendingSteps.length === 1) {
        state.pacingTimer = setTimeout(revealNextPendingStep, PACING_DELAY_MS);
      }
    }

    if (state.pendingSteps.length > 0 || state.pacingTimer) {
      // Steps still queued — publish the flag so the mirror doesn't lag the ref and show the answer
      // through the pacing gap.
      state.toolPacingComplete = false;
      setToolPacingComplete(false);
    }
  }, [
    toolTurnGroups,
    stopPacketSeen,
    finalAnswerComing,
    nodeIdStr,
    revealNextPendingStep,
    publish,
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
        revealedStepKeys.has(step.key),
      );
      if (revealedSteps.length > 0) {
        result.push({
          turnIndex: turnGroup.turnIndex,
          steps: revealedSteps,
          isParallel: revealedSteps.length > 1,
        });
      }
    }
    return result;
  }, [toolTurnGroups, revealedStepKeys, shouldBypassPacing]);

  const pacedDisplayGroups = useMemo(
    () =>
      shouldBypassPacing || toolPacingComplete || stopPacketSeen
        ? displayGroups
        : [],
    [shouldBypassPacing, toolPacingComplete, stopPacketSeen, displayGroups],
  );

  const pacedFinalAnswerComing = useMemo(
    () => (shouldBypassPacing || toolPacingComplete) && finalAnswerComing,
    [shouldBypassPacing, toolPacingComplete, finalAnswerComing],
  );

  return { pacedTurnGroups, pacedDisplayGroups, pacedFinalAnswerComing };
}
